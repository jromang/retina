"""Star removal (inpaint backend)."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image, get


def _field_with_stars(h=96, w=96, n=25, seed=5):
    rng = np.random.default_rng(seed)
    bg = 0.1 + 0.05 * (np.mgrid[0:h, 0:w][1] / w)  # slight background gradient
    img = bg.astype(np.float32) + rng.normal(0, 0.005, (h, w)).astype(np.float32)
    for _ in range(n):
        cy, cx = rng.uniform(8, h - 8), rng.uniform(8, w - 8)
        ys, xs = np.mgrid[0:h, 0:w]
        img += (
            0.8 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.5**2)))
        ).astype(np.float32)
    return np.clip(img, 0, 1)


def test_star_removal_inpaint_removes_bright_stars():
    field = _field_with_stars()
    img = Image(field[:, :, None])
    out = get("StarRemoval")(
        mode="inpaint", fwhm=3.0, threshold_sigma=4.0, radius=6.0
    ).execute_on_image(img)
    # inpainting removes most of the stellar content (bright pixels) without touching the background
    before = int((field > 0.5).sum())
    after = int((out.data > 0.5).sum())
    assert before > 0 and after < before * 0.3  # >70 % of the stellar pixels removed
    assert abs(float(out.data.mean()) - 0.125) < 0.05  # background ~0.1–0.15 preserved


def test_external_mode_requires_command():
    img = Image(np.zeros((8, 8, 1), dtype=np.float32))
    with pytest.raises(ValueError):
        get("StarRemoval")(mode="external").execute_on_image(img)


def _make_scale_onnx(path, factor=0.5):
    """Toy ONNX model: output = input * factor (dynamic NCHW)."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, None, None])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, None, None])
    scale = numpy_helper.from_array(np.array(factor, dtype=np.float32), name="scale")
    node = helper.make_node("Mul", ["input", "scale"], ["output"])
    graph = helper.make_graph([node], "starless", [x], [y], [scale])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, path)


def test_onnx_backend_tiling_reconstructs(tmp_path):
    pytest.importorskip("onnxruntime")
    model_path = str(tmp_path / "scale.onnx")
    _make_scale_onnx(model_path, factor=0.5)

    rng = np.random.default_rng(0)
    img = Image((rng.random((150, 170, 3)) * 0.8 + 0.1).astype(np.float32))
    out = get("StarRemoval")(
        mode="onnx", model=model_path, tile_size=64, overlap=16
    ).execute_on_image(img)
    # tiling + blending must reconstruct exactly 0.5 * input
    np.testing.assert_allclose(out.data, img.data * 0.5, atol=1e-4)


def test_onnx_mode_requires_model():
    img = Image(np.zeros((8, 8, 3), dtype=np.float32))
    with pytest.raises(ValueError):
        get("StarRemoval")(mode="onnx").execute_on_image(img)
