"""The process runs headless (no shell) — the console-completeness pillar."""

from __future__ import annotations

import numpy as np
from retina import GaussianConvolution, Image, View


def test_gaussian_preserves_shape(synthetic_image):
    out = GaussianConvolution(sigma=2.0).execute_on_image(synthetic_image)
    assert out.data.shape == synthetic_image.data.shape
    assert out.data.dtype == np.float32


def test_gaussian_smooths_point(synthetic_image):
    """The convolution spreads the point-like star: the peak drops, its neighbours rise."""
    h, w = synthetic_image.height, synthetic_image.width
    peak_before = synthetic_image.sample(w // 2, h // 2)
    out = GaussianConvolution(sigma=2.0).execute_on_image(synthetic_image)
    peak_after = out.sample(w // 2, h // 2)
    neighbour_after = out.sample(w // 2 + 1, h // 2)
    neighbour_before = synthetic_image.sample(w // 2 + 1, h // 2)
    assert peak_after < peak_before
    assert neighbour_after > neighbour_before


def test_sigma_zero_is_identity(synthetic_image):
    out = GaussianConvolution(sigma=0.0).execute_on_image(synthetic_image)
    np.testing.assert_allclose(out.data, synthetic_image.data, atol=1e-6)


def test_execute_on_view_pushes_history():
    view = View(Image(np.zeros((16, 16, 1), dtype=np.float32) + 0.5), view_id="test")
    assert view.history_index == 0
    GaussianConvolution(sigma=1.5).execute_on(view)
    assert view.history_index == 1
    assert view.can_go_backward
    view.undo()
    assert view.history_index == 0
    assert not view.can_go_backward


def test_to_python_source_roundtrip():
    src = GaussianConvolution(sigma=3.5).to_python_source("view")
    assert src == "GaussianConvolution(sigma=3.5).execute_on(view)"


# --- the `view` parameter type ------------------------------------------------------------

def _all_parameters():
    """(process_id, Parameter) for the whole registered catalogue."""
    import retina

    for process_id, cls in retina.all_processes().items():
        for param in cls.parameters:
            yield process_id, param


def test_every_parameter_naming_a_view_is_typed_view():
    """The guard that keeps the form honest.

    A parameter that designates another view is rendered as a picker of the open views; one
    left as `str` is a blank box in which an identifier has to be recalled from memory — and a
    typo does not fail there, the domain falls back on the current image. Since the only thing
    distinguishing the two is the type, this walks the labels and refuses the divergence.
    """
    guilty = [
        f"{pid}.{p.id}"
        for pid, p in _all_parameters()
        if ("view" in p.label.lower() or "preview" in p.label.lower()) and p.type != "view"
    ]
    assert guilty == []


def test_a_view_parameter_is_a_string_that_defaults_to_empty():
    """`view` is a `str` to the domain: same coercion, same serialization, same replay.

    Empty is the meaningful default everywhere — "reuse the current image", "gray-world",
    "the active window" — and the form keeps an explicit empty entry for it.
    """
    for pid, param in _all_parameters():
        if param.type != "view":
            continue
        assert param.default == "", f"{pid}.{param.id}"
        assert param.coerce("Image01") == "Image01"
        assert param.coerce("") == ""


def test_the_view_type_reaches_the_client_verbatim():
    """It is the type, and nothing else, that makes the interface draw a picker."""
    from retina.processes.channels import ChannelCombination

    types = {p.id: p.type for p in ChannelCombination.parameters}
    assert types == {"r": "view", "g": "view", "b": "view"}
