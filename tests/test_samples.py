"""Sample raw datasets — manifest, verified download, extraction, console parity.

No test touches the real network: the manifest is diverted through ``RETINA_SAMPLES_MANIFEST``
and the archives are served by an ephemeral local HTTP server. It is the only way to exercise
the fingerprint, the extraction and the cancellation without depending on the machine's
connection — and without downloading a hundred and sixty megabytes on every ``pytest -q``.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from retina import samples
from retina.process import context
from retina.process.progress import ProcessCancelled, ProgressMonitor


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


def write_manifest(tmp_path, monkeypatch, entries, default=""):
    path = tmp_path / "samples.json"
    content = {"schema": 1, "samples": entries}
    if default:
        content["default"] = default
    path.write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setenv(samples.ENV_MANIFEST, str(path))
    return path


def toy_archive(path, *, root="toy-night", files=("light_1.fits", "light_2.fits")):
    """A tar.bz2 archive with a single folder, like the ones we really download."""
    with tarfile.open(path, "w:bz2") as tf:
        for name in files:
            payload = f"contents of {name}".encode()
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return path


def _publish(tmp_path, monkeypatch, server, ident, *, sha=None, name="dataset.tar.bz2", **kw):
    """Publishes a toy archive under an identifier **specific to the test**.

    The cache lives at session scope: two tests sharing an identifier would re-use each
    other's folder, and `download` would return through its resume path before having
    verified anything at all.
    """
    archive = toy_archive(tmp_path / name, **kw)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest() if sha is None else sha
    write_manifest(tmp_path, monkeypatch, [{
        "id": ident, "name": "Toy dataset", "url": f"{server}/{name}",
        "sha256": digest, "size": archive.stat().st_size,
        "license": "CC-BY-4.0", "attribution": "Nobody", "doi": "10.0000/toy",
    }])
    return digest


# --- the embedded manifest ---------------------------------------------------------------

def test_the_embedded_manifest_only_promises_what_is_verifiable():
    """The rule: no entry without a licence, a fingerprint and a durable identifier.

    An unverifiable URL produces the kind of failure nobody can diagnose — the user clicks,
    it fails, and nothing says whether it is their network, our link or the far-end server.
    """
    catalog = samples.load_manifest(samples.manifest_path())

    assert catalog, "the embedded manifest is empty"
    for set_ in catalog:
        assert set_.url.startswith("https://"), set_.id
        assert re.fullmatch(r"[0-9a-f]{64}", set_.sha256), set_.id
        assert set_.size > 0, set_.id
        assert set_.license, set_.id
        assert set_.attribution, set_.id
        # The DOI is what survives a domain name change, the URL is not.
        assert set_.doi, set_.id


def test_the_default_points_at_a_real_entry():
    """The welcome card calls without an identifier: the default cannot be a phantom."""
    default = samples.default_id()

    assert default
    assert samples.spec(default).id == default


def test_the_default_is_the_smallest_dataset():
    """It is the only criterion that matters to a newcomer: how long they have to wait."""
    catalog = samples.load_manifest(samples.manifest_path())

    assert samples.default_id() == min(catalog, key=lambda j: j.size).id


def test_a_missing_manifest_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv(samples.ENV_MANIFEST, str(tmp_path / "nothing.json"))

    assert samples.catalog() == []
    with pytest.raises(KeyError, match="unknown sample dataset"):
        samples.spec("anything-at-all")


def test_a_newer_schema_is_refused_rather_than_misread(tmp_path, monkeypatch):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema": 99, "samples": []}), encoding="utf-8")
    monkeypatch.setenv(samples.ENV_MANIFEST, str(path))

    with pytest.raises(ValueError, match="please update Retina"):
        samples.load_manifest()


def test_the_default_is_declared_and_not_guessed(tmp_path, monkeypatch):
    entries = [
        {"id": "big", "name": "Big", "url": "", "sha256": "", "size": 9},
        {"id": "small", "name": "Small", "url": "", "sha256": "", "size": 1},
    ]
    write_manifest(tmp_path, monkeypatch, entries, default="small")

    assert samples.default_id() == "small"
    # …and without a declaration it is the first entry: a default, never nothing.
    write_manifest(tmp_path.parent, monkeypatch, entries)
    assert samples.default_id() == "big"


# --- download, fingerprint, extraction ---------------------------------------------------

def test_a_dataset_downloads_verifies_and_unpacks(tmp_path, monkeypatch, server):
    digest = _publish(tmp_path, monkeypatch, server, "toy-ok")
    assert not samples.is_downloaded("toy-ok")

    folder = samples.download("toy-ok")

    # `path` descends into the archive's single folder: that is the one we pre-process.
    assert folder.name == "toy-night"
    assert sorted(f.name for f in folder.iterdir()) == ["light_1.fits", "light_2.fits"]
    assert samples.is_downloaded("toy-ok")
    assert not samples.sample_dir("toy-ok").with_name("toy-ok.part").exists()
    # The stamp keeps what was verified — enough to diagnose without re-downloading.
    control = json.loads((samples.sample_dir("toy-ok") / samples.STAMP).read_text())
    assert control["sha256"] == digest
    assert control["license"] == "CC-BY-4.0"


def test_a_fingerprint_that_does_not_match_discards_everything(tmp_path, monkeypatch, server):
    _publish(tmp_path, monkeypatch, server, "toy-sha", sha="0" * 64)

    with pytest.raises(ValueError, match="wrong fingerprint"):
        samples.download("toy-sha")

    assert not samples.is_downloaded("toy-sha")
    assert not samples.sample_dir("toy-sha").exists()


def test_the_download_reports_its_progress_and_can_be_cancelled(tmp_path, monkeypatch, server):
    _publish(tmp_path, monkeypatch, server, "toy-cancel",
             files=[f"light_{i:03d}.fits" for i in range(400)])
    monitor = ProgressMonitor()
    fractions: list[float | None] = []

    def follow(fraction, message=""):
        fractions.append(fraction)
        monitor.cancel()

    monitor.on_progress = follow
    context.set_monitor(monitor)
    try:
        with pytest.raises(ProcessCancelled):
            samples.download("toy-cancel")
    finally:
        context.set_monitor(None)

    assert fractions
    # No half-extracted folder — which would pass for a complete dataset — and no orphan `.part`.
    assert not samples.is_downloaded("toy-cancel")
    assert not samples.sample_dir("toy-cancel").exists()
    assert not samples.sample_dir("toy-cancel").with_name("toy-cancel.part").exists()


def test_ensure_does_not_redownload_what_is_already_there(tmp_path, monkeypatch, server):
    _publish(tmp_path, monkeypatch, server, "toy-resume")
    first = samples.ensure("toy-resume")
    mtime = (first / "light_1.fits").stat().st_mtime_ns

    # The server is still up, but `ensure` must not even reach for it.
    (tmp_path / "dataset.tar.bz2").unlink()
    assert samples.ensure("toy-resume") == first
    assert (first / "light_1.fits").stat().st_mtime_ns == mtime


def test_ensure_refuses_an_unknown_id_before_touching_the_network(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch, [])

    with pytest.raises(KeyError, match="available"):
        samples.ensure("never-seen")


def test_an_archive_that_escapes_its_folder_is_refused(tmp_path, monkeypatch, server):
    """The manifest is ours, the archives are not: we do not unpack on trust.

    Zip and tar are handled separately — ``filter="data"`` covers the latter, the former
    requires an explicit check on the names.
    """
    hostile = tmp_path / "hostile.zip"
    with zipfile.ZipFile(hostile, "w") as zf:
        zf.writestr("../escaped.txt", "no")
    digest = hashlib.sha256(hostile.read_bytes()).hexdigest()
    write_manifest(tmp_path, monkeypatch, [{
        "id": "toy-hostile", "name": "Hostile", "url": f"{server}/hostile.zip",
        "sha256": digest, "size": hostile.stat().st_size,
    }])

    with pytest.raises(ValueError, match="escapes its folder"):
        samples.download("toy-hostile")

    assert not (samples.sample_dir("toy-hostile").parent / "escaped.txt").exists()
    assert not samples.is_downloaded("toy-hostile")


def test_a_folder_with_several_roots_stays_at_the_root(tmp_path, monkeypatch, server):
    """A flat archive has no folder to descend into — we return the cache folder itself."""
    archive = tmp_path / "flat.tar.bz2"
    with tarfile.open(archive, "w:bz2") as tf:
        for name in ("a.fits", "b.fits"):
            info = tarfile.TarInfo(name)
            info.size = 3
            tf.addfile(info, io.BytesIO(b"abc"))
    write_manifest(tmp_path, monkeypatch, [{
        "id": "toy-flat", "name": "Flat", "url": f"{server}/flat.tar.bz2",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "size": archive.stat().st_size,
    }])

    folder = samples.download("toy-flat")

    assert folder == samples.sample_dir("toy-flat")
    assert sorted(f.name for f in folder.iterdir() if f.suffix == ".fits") == ["a.fits", "b.fits"]


# --- console parity -----------------------------------------------------------------------

def test_app_download_sample_echoes_the_equivalent_python(tmp_path, monkeypatch, server):
    """Console-completeness pillar: the welcome screen's gesture writes itself in the console."""
    from retina.app import Application

    _publish(tmp_path, monkeypatch, server, "toy-echo")
    app = Application()
    echoes: list[str] = []
    app.on_echo = echoes.append

    folder = app.download_sample("toy-echo")

    assert echoes == ["app.download_sample('toy-echo')"]
    assert folder.endswith("toy-night")


def test_a_failure_echoes_nothing(tmp_path, monkeypatch, server):
    """A console line that did not succeed would teach something untrue."""
    from retina.app import Application

    _publish(tmp_path, monkeypatch, server, "toy-echo-failed", sha="0" * 64)
    app = Application()
    echoes: list[str] = []
    app.on_echo = echoes.append

    with pytest.raises(ValueError):
        app.download_sample("toy-echo-failed")

    assert echoes == []


def test_the_download_leaves_a_trace_in_the_notifications(tmp_path, monkeypatch,
                                                          server):
    """Start and finish: without them, two minutes of silence for the user."""
    from retina.app import Application

    _publish(tmp_path, monkeypatch, server, "toy-notif")
    app = Application()

    app.download_sample("toy-notif")

    messages = [n.message for n in app.notifications]
    assert any("Downloading" in m for m in messages)
    assert any("ready" in m for m in messages)


def test_the_default_is_called_without_argument_and_echoes_the_resolved_name(tmp_path,
                                                                            monkeypatch,
                                                                            server):
    """This is what the welcome card does: `app.download_sample()`, knowing nothing.

    The echo, though, names the dataset: `app.download_sample('')` would not tell which
    one was taken.
    """
    from retina.app import Application

    _publish(tmp_path, monkeypatch, server, "toy-default")
    app = Application()
    echoes: list[str] = []
    app.on_echo = echoes.append

    assert app.download_sample().endswith("toy-night")
    assert echoes == ["app.download_sample('toy-default')"]
