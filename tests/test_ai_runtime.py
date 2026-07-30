"""The local AI layer: factored ONNX runtime, manifest, downloads.

No test touches the real network: the manifest is diverted through ``RETINA_MODELS_MANIFEST``
and downloads go through an ephemeral local HTTP server. That is the only way to exercise
fingerprinting, resumption and cancellation without depending on the machine's connection.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest
from retina.ai import models as ai_models
from retina.ai import onnx as ai_onnx
from retina.model.image import Image
from retina.process import context
from retina.process.progress import ProcessCancelled, ProgressMonitor
from retina.process.registry import get


def toy_model(path, factor=0.5):
    """Minimal ONNX model: output = input × factor (dynamic NCHW)."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, None, None])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, None, None])
    scale = numpy_helper.from_array(np.array(factor, dtype=np.float32), name="scale")
    node = helper.make_node("Mul", ["input", "scale"], ["output"])
    graph = helper.make_graph([node], "toy", [x], [y], [scale])
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]), str(path))


@pytest.fixture
def server(tmp_path):
    """Serves ``tmp_path`` over HTTP on a free port, for the duration of the test."""
    root = tmp_path

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # name imposed by BaseHTTPRequestHandler
            file = root / self.path.lstrip("/")
            if not file.is_file():
                self.send_error(404)
                return
            payload = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def write_manifest(tmp_path, monkeypatch, entries):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1, "models": entries}), encoding="utf-8")
    monkeypatch.setenv(ai_models.ENV_MANIFEST, str(path))
    return path


# --- the runtime ----------------------------------------------------------------------

def test_tiling_and_blending_reconstruct_the_input(tmp_path):
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)
    rng = np.random.default_rng(0)
    data = (rng.random((150, 170, 3)) * 0.8 + 0.1).astype(np.float32)

    output = ai_onnx.run_tiled(data, ai_onnx.open_session(str(path)),
                               tile_size=64, overlap=16)

    np.testing.assert_allclose(output, data * 0.5, atol=1e-4)


def test_a_single_plane_goes_through_the_rgb_model(tmp_path):
    """These models are trained in RGB: a mono image is replicated then re-averaged."""
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)
    data = np.full((40, 40, 1), 0.6, dtype=np.float32)

    output = ai_onnx.run_tiled(data, ai_onnx.open_session(str(path)), tile_size=32, overlap=8)

    assert output.shape == (40, 40, 1)
    np.testing.assert_allclose(output, 0.3, atol=1e-4)


def test_every_tile_is_reported(tmp_path):
    """This is what was missing: four hundred silent inferences on a large image."""
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path)
    reports: list[tuple[float, int, int]] = []

    ai_onnx.run_tiled(np.full((128, 128, 3), 0.4, dtype=np.float32),
                      ai_onnx.open_session(str(path)), tile_size=32, overlap=8,
                      progress=lambda f, n, t: reports.append((f, n, t)))

    assert len(reports) == reports[0][2] > 1
    assert [n for _, n, _ in reports] == list(range(1, len(reports) + 1))
    assert reports[-1][0] == pytest.approx(1.0)


def test_the_session_is_memoised_then_reloaded_if_the_file_changes(tmp_path):
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)
    ai_onnx.forget_sessions()

    first = ai_onnx.open_session(str(path))
    assert ai_onnx.open_session(str(path)) is first

    toy_model(path, 0.25)
    import os
    os.utime(path, (0, 0))  # different mtime → the cache must let go
    assert ai_onnx.open_session(str(path)) is not first


def test_a_missing_model_says_so_before_inferring(tmp_path):
    with pytest.raises(FileNotFoundError, match="ONNX model not found"):
        ai_onnx.open_session(str(tmp_path / "nowhere.onnx"))
    with pytest.raises(ValueError, match="empty model path"):
        ai_onnx.open_session("")


def test_star_removal_now_reports_its_tiles(tmp_path):
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path)
    reports: list[str] = []
    monitor = ProgressMonitor()
    monitor.on_progress = lambda f, msg="": reports.append(msg)
    context.set_monitor(monitor)
    try:
        get("StarRemoval")(mode="onnx", model=str(path), tile_size=32,
                           overlap=8).execute_on_image(
            Image(np.full((96, 96, 3), 0.4, dtype=np.float32)))
    finally:
        context.set_monitor(None)

    assert any("tile" in m for m in reports)


# --- the manifest ---------------------------------------------------------------------

def test_the_embedded_manifest_lists_the_graxpert_models():
    """They are re-hosted on Hugging Face (CC BY-NC-SA mirror), each with its fingerprint."""
    models = ai_models.load_manifest(ai_models.manifest_path())

    tasks = {m.task for m in models}
    assert {"denoise", "background", "deconv_object", "deconv_stellar"} <= tasks
    for model in models:
        assert model.url.startswith("https://huggingface.co/")
        assert len(model.sha256) == 64
        assert model.license == "CC-BY-NC-SA-4.0"


def test_a_missing_manifest_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv(ai_models.ENV_MANIFEST, str(tmp_path / "nothing.json"))
    assert ai_models.available() == []


def test_a_newer_schema_is_refused_rather_than_misread(tmp_path, monkeypatch):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema": 99, "models": []}), encoding="utf-8")
    monkeypatch.setenv(ai_models.ENV_MANIFEST, str(path))

    with pytest.raises(ValueError, match="please update Retina"):
        ai_models.load_manifest()


def test_models_can_be_filtered_by_task(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch, [
        {"id": "a", "task": "denoise", "name": "A", "version": "1", "url": "", "sha256": ""},
        {"id": "b", "task": "starless", "name": "B", "version": "1", "url": "", "sha256": ""},
    ])

    assert [m.id for m in ai_models.available("denoise")] == ["a"]
    assert len(ai_models.available()) == 2
    assert ai_models.spec("b").label == "B 1"
    with pytest.raises(KeyError, match="unknown model"):
        ai_models.spec("c")


# --- downloading ----------------------------------------------------------------------

def _publish(tmp_path, monkeypatch, server, ident, content=b"x" * 300_000, sha=None):
    """Publishes a toy model under an identifier **specific to the test**.

    The model cache lives at session scope: two tests sharing an identifier would help
    themselves to each other's file, and `download` would bail out through its resume path
    before having checked anything.
    """
    (tmp_path / "m.onnx").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest() if sha is None else sha
    write_manifest(tmp_path, monkeypatch, [{
        "id": ident, "task": "denoise", "name": "Toy", "version": "1.0",
        "url": f"{server}/m.onnx", "sha256": digest, "size": len(content),
    }])
    return digest


def test_a_model_is_downloaded_and_its_fingerprint_verified(tmp_path, monkeypatch, server):
    digest = _publish(tmp_path, monkeypatch, server, "toy-ok")
    assert not ai_models.is_downloaded("toy-ok")

    path = ai_models.download("toy-ok")

    assert path.exists() and ai_models.is_downloaded("toy-ok")
    assert ai_models.sha256_of(path) == digest
    assert not path.with_suffix(path.suffix + ".part").exists()


def test_a_fingerprint_that_does_not_match_discards_the_file(tmp_path, monkeypatch, server):
    _publish(tmp_path, monkeypatch, server, "toy-sha", sha="0" * 64)

    with pytest.raises(ValueError, match="wrong fingerprint"):
        ai_models.download("toy-sha")

    assert not ai_models.is_downloaded("toy-sha")


def test_the_download_reports_its_progress_and_can_be_cancelled(tmp_path, monkeypatch, server):
    _publish(tmp_path, monkeypatch, server, "toy-cancel", content=b"y" * (5 << 20))
    monitor = ProgressMonitor()
    fractions: list[float | None] = []

    def track(fraction, message=""):
        fractions.append(fraction)
        if len(fractions) == 2:
            monitor.cancel()

    monitor.on_progress = track
    context.set_monitor(monitor)
    try:
        with pytest.raises(ProcessCancelled):
            ai_models.download("toy-cancel")
    finally:
        context.set_monitor(None)

    assert len(fractions) >= 2
    # Neither a truncated model, nor an abandoned `.part` that would pass for a download
    # still in progress.
    assert not ai_models.is_downloaded("toy-cancel")
    assert not ai_models.model_path("toy-cancel").with_suffix(".onnx.part").exists()


def test_the_ai_processes_record_the_model_they_used(tmp_path):
    """The whole point: the model enters the instance, hence everything that serialises it."""
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)
    digest = ai_models.sha256_of(path)

    process = get("AIDenoise")(model=str(path), tile_size=32, overlap=8)
    output = process.execute_on_image(Image(np.full((64, 64, 3), 0.6, dtype=np.float32)))

    np.testing.assert_allclose(output.data, 0.3, atol=1e-4)
    assert process.model_sha256 == digest
    # …and the fingerprint travels through serialisation, without any format having to change.
    assert process.to_dict()["values"]["model_sha256"] == digest
    assert digest in process.to_python_source()


def test_traceability_reaches_the_fits_keywords(tmp_path):
    pytest.importorskip("onnxruntime")
    from retina.app import Application

    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)
    app = Application()
    window = app.new_window(Image(np.full((48, 48, 3), 0.6, dtype=np.float32)), window_id="w")

    get("AIDenoise")(model=str(path), tile_size=32, overlap=8).execute_on(window.main_view)

    assert window.keywords["AIMODEL"][0] == "scale.onnx"
    assert window.keywords["AIMODSHA"][0] == ai_models.sha256_of(path)[:16]


def test_a_fingerprint_that_changed_warns_without_interrupting(tmp_path):
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)

    process = get("AIDenoise")(model=str(path), tile_size=32, overlap=8,
                               model_sha256="0" * 64)
    process.execute_on_image(Image(np.full((48, 48, 3), 0.6, dtype=np.float32)))

    # The processing did take place, and the recorded fingerprint was brought up to date.
    assert process.model_sha256 == ai_models.sha256_of(path)


def toy_background_model(path):
    """Minimal BGE model: NHWC input ``gen_input_image`` [1,256,256,3] → identity.

    The real GraXpert model returns a background; the identity is enough to exercise our
    chain (downscale → normalise → infer → denormalise → upscale), which it closes neatly:
    the estimated "background" becomes the smoothed, downscaled image again.
    """
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("gen_input_image", TensorProto.FLOAT, [1, 256, 256, 3])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 256, 256, 3])
    node = helper.make_node("Identity", ["gen_input_image"], ["output"])
    graph = helper.make_graph([node], "bge", [x], [y])
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]), str(path))


def test_the_ai_background_backend_estimates_then_subtracts(tmp_path):
    """The ``ai`` backend of ``BackgroundExtraction``: one full-frame inference, no tiling."""
    pytest.importorskip("onnxruntime")
    path = tmp_path / "bge.onnx"
    toy_background_model(path)

    # Gentle linear gradient: the estimated background must follow it, and the subtraction
    # must flatten it.
    y = np.linspace(0.2, 0.6, 96, dtype=np.float32)[:, None]
    data = np.repeat(np.repeat(y, 96, axis=1)[:, :, None], 3, axis=2)

    process = get("BackgroundExtraction")(backend="ai", model=str(path), subtract=True,
                                          pedestal=0.1)
    output = process.execute_on_image(Image(data))

    # Background removed (identity model ⇒ background ≈ smoothed image): the pedestal is
    # left, flat.
    assert float(np.std(output.data)) < 0.02
    np.testing.assert_allclose(output.data.mean(), 0.1, atol=0.03)
    assert process.model_sha256 == ai_models.sha256_of(path)


def test_the_ai_background_backend_handles_mono(tmp_path):
    """A mono image is replicated into three channels for the network, then folded back."""
    pytest.importorskip("onnxruntime")
    path = tmp_path / "bge.onnx"
    toy_background_model(path)

    data = np.full((64, 80, 1), 0.4, dtype=np.float32)
    process = get("BackgroundExtraction")(backend="ai", model=str(path), subtract=False)
    background = process.execute_on_image(Image(data))

    assert background.data.shape == (64, 80, 1)          # same geometry as the input
    np.testing.assert_allclose(background.data.mean(), 0.4, atol=0.03)


def _without_catalog(tmp_path, monkeypatch):
    """Neither manifest nor GraXpert install: the catalogue really is empty."""
    write_manifest(tmp_path, monkeypatch, [])
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(tmp_path / "nowhere"))


def test_with_no_model_at_all_the_process_says_what_to_do(tmp_path, monkeypatch):
    """Empty catalogue: `latest` finds nothing, and the message says where to look."""
    _without_catalog(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="no model available"):
        get("AIDenoise")().execute_on_image(Image(np.zeros((16, 16, 3), dtype=np.float32)))
    with pytest.raises(ValueError, match="model not found"):
        get("AIDeconvolution")(model="/no/where.onnx").execute_on_image(
            Image(np.zeros((16, 16, 3), dtype=np.float32)))


def test_the_selector_reflects_the_live_catalog(tmp_path, monkeypatch):
    """The drop-down is computed on the fly: a local model that appears shows up in it."""
    root = graxpert_install(tmp_path, tasks=("denoise",), versions=("9.9.9",))
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))

    choice = get("AIDenoise").parameter_choices("model_id")

    assert choice[0] == "latest"
    assert "graxpert-denoise-9.9.9" in choice          # the local model is offered
    # …and it wins: `latest` takes the local version, not the embedded manifest's.
    assert ai_models.latest_for_task("denoise").id == "graxpert-denoise-9.9.9"


def test_the_latest_default_picks_the_most_recent(tmp_path, monkeypatch):
    """Opening and running is enough: `latest` resolves the most recent model for the task.

    Local versions are deliberately chosen **above** those of the embedded manifest: otherwise
    `latest` would pick the HF mirror version (more recent) and want to download it. That this
    happens is in fact correct — it is the behaviour when no local model is newer."""
    pytest.importorskip("onnxruntime")
    root = graxpert_install(tmp_path, tasks=("denoise",), versions=("9.9.8", "9.9.9"))
    toy_model(root / "denoise-ai-models" / "9.9.9" / "model.onnx", 0.5)
    toy_model(root / "denoise-ai-models" / "9.9.8" / "model.onnx", 0.25)
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))

    process = get("AIDenoise")(tile_size=32, overlap=8)     # model_id default = "latest"
    output = process.execute_on_image(Image(np.full((48, 48, 3), 0.6, dtype=np.float32)))

    assert process.model_version == "9.9.9"                 # the most recent, not 9.9.8
    np.testing.assert_allclose(output.data, 0.3, atol=1e-4)  # 0.6 × 0.5


def test_strength_doses_the_effect(tmp_path):
    pytest.importorskip("onnxruntime")
    path = tmp_path / "scale.onnx"
    toy_model(path, 0.5)
    source = Image(np.full((48, 48, 3), 0.6, dtype=np.float32))

    half = get("AIDenoise")(model=str(path), strength=0.5, tile_size=32,
                            overlap=8).execute_on_image(source)

    np.testing.assert_allclose(half.data, 0.45, atol=1e-4)  # 0.6·0.5 + 0.3·0.5


def test_the_ai_deconvolution_picks_its_task_from_the_target():
    assert get("AIDeconvolution")(target="object").task == "deconv_object"
    assert get("AIDeconvolution")(target="stellar").task == "deconv_stellar"


def test_ensure_does_not_redownload_what_is_already_there(tmp_path, monkeypatch, server):
    _publish(tmp_path, monkeypatch, server, "toy-resume")
    first = ai_models.ensure("toy-resume")
    mark = first.stat().st_mtime_ns

    # The server is still up, but `ensure` must not even ask it.
    (tmp_path / "m.onnx").unlink()
    assert ai_models.ensure("toy-resume") == first
    assert first.stat().st_mtime_ns == mark


# --- discovering a GraXpert installation ----------------------------------------------

def graxpert_install(root, tasks=("denoise", "deconv_object"), versions=("1.0.0",)):
    """Reproduces the tree GraXpert creates in its data folder."""
    folders = ai_models.GRAXPERT_DIRS
    for task in tasks:
        for version in versions:
            target = root / folders[task] / version
            target.mkdir(parents=True, exist_ok=True)
            (target / "model.onnx").write_bytes(b"\x00" * 4096)
    return root


def test_the_models_of_a_graxpert_install_are_found(tmp_path, monkeypatch):
    """We cannot distribute them; the user who has them must not have to go looking."""
    monkeypatch.setenv(ai_models.ENV_GRAXPERT,
                       str(graxpert_install(tmp_path, versions=("1.0.0", "1.1.0"))))

    found_items = ai_models.discover_local()

    assert {m.task for m in found_items} == {"denoise", "deconv_object"}
    assert {m.version for m in found_items} == {"1.0.0", "1.1.0"}
    assert all(m.license == "CC-BY-NC-SA-4.0" for m in found_items)


def test_a_discovered_model_carries_its_non_commercial_license(tmp_path, monkeypatch):
    """This is what the user cannot guess, and what traceability has to carry."""
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(graxpert_install(tmp_path)))

    definition = ai_models.spec("graxpert-denoise-1.0.0")

    assert definition.license == ai_models.GRAXPERT_LICENSE
    assert "NC" in definition.license


def test_a_discovered_model_is_not_copied_into_our_cache(tmp_path, monkeypatch):
    """Duplicating it would cost hundreds of megabytes and make the two copies diverge at
    the first GraXpert update."""
    root = graxpert_install(tmp_path)
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))

    path = ai_models.ensure("graxpert-denoise-1.0.0")

    assert path == root / "denoise-ai-models" / "1.0.0" / "model.onnx"
    assert not ai_models.model_path("graxpert-denoise-1.0.0").exists()


def test_an_uninstalled_model_leaves_the_catalog(tmp_path, monkeypatch):
    """Discovery is redone on every call: uninstalling GraXpert removes its models
    without our having to invalidate anything."""
    root = graxpert_install(tmp_path)
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))
    definition = ai_models.spec("graxpert-denoise-1.0.0")

    pathlib.Path(definition.path).unlink()

    assert "graxpert-denoise-1.0.0" not in {m.id for m in ai_models.catalog()}
    with pytest.raises(KeyError, match="available"):
        ai_models.spec("graxpert-denoise-1.0.0")


def test_without_an_install_discovery_returns_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(tmp_path / "nowhere"))

    assert ai_models.discover_local() == []
    # The catalogue is not empty for all that: the embedded manifest (HF mirror) is still there.
    assert all(m.path == "" for m in ai_models.catalog())


def test_the_process_resolves_a_discovered_model(tmp_path, monkeypatch):
    pytest.importorskip("onnxruntime")
    root = graxpert_install(tmp_path)
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))
    # Replace the dummy file with a real toy model, so as to go all the way.
    toy_model(root / "denoise-ai-models" / "1.0.0" / "model.onnx", 0.5)

    process = get("AIDenoise")(model_id="graxpert-denoise-1.0.0", tile_size=32, overlap=8)
    output = process.execute_on_image(Image(np.full((64, 64, 3), 0.6, dtype=np.float32)))

    np.testing.assert_allclose(output.data, 0.3, atol=1e-4)
    # Traceability does not change: it is the fingerprint of the file actually used.
    assert process.model_sha256 == ai_models.sha256_of(
        root / "denoise-ai-models" / "1.0.0" / "model.onnx")
    assert process.model_version == "1.0.0"


def test_the_searched_locations_depend_on_the_platform(monkeypatch):
    monkeypatch.delenv(ai_models.ENV_GRAXPERT, raising=False)

    monkeypatch.setattr(ai_models.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/data")
    assert ai_models.graxpert_data_dirs() == [pathlib.Path("/tmp/data/GraXpert")]

    monkeypatch.setattr(ai_models.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/x/AppData/Local")
    # appdirs repeats the application name when no author is given: both variants exist in
    # the wild, only one at a time.
    assert len(ai_models.graxpert_data_dirs()) == 2


# --- local discovery takes priority over the manifest ---------------------------------

def test_a_local_model_beats_its_namesake_in_the_manifest(tmp_path, monkeypatch):
    """Both carry the same id: an already installed model must not be downloaded again."""
    # Manifest with a URL entry, same id as a GraXpert install would produce.
    write_manifest(tmp_path, monkeypatch, [{
        "id": "graxpert-denoise-3.0.2", "task": "denoise", "name": "GraXpert denoise",
        "version": "3.0.2", "url": "https://example.invalid/m.onnx", "sha256": "0" * 64,
    }])
    root = tmp_path / "gx"
    (root / "denoise-ai-models" / "3.0.2").mkdir(parents=True)
    (root / "denoise-ai-models" / "3.0.2" / "model.onnx").write_bytes(b"\x00" * 4096)
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))

    definition = ai_models.spec("graxpert-denoise-3.0.2")

    # It is the local entry (a path, no URL) that wins — hence no download at all.
    assert definition.path
    assert not definition.url
    assert ai_models.ensure("graxpert-denoise-3.0.2") == (
        root / "denoise-ai-models" / "3.0.2" / "model.onnx")


def test_the_catalog_deduplicates_by_id(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch, [{
        "id": "graxpert-denoise-3.0.2", "task": "denoise", "name": "x",
        "version": "3.0.2", "url": "https://example.invalid/m.onnx", "sha256": "0" * 64,
    }])
    root = tmp_path / "gx"
    (root / "denoise-ai-models" / "3.0.2").mkdir(parents=True)
    (root / "denoise-ai-models" / "3.0.2" / "model.onnx").write_bytes(b"\x00" * 16)
    monkeypatch.setenv(ai_models.ENV_GRAXPERT, str(root))

    ids = [m.id for m in ai_models.catalog()]

    assert ids.count("graxpert-denoise-3.0.2") == 1
