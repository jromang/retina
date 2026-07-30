"""Generate the parity fixtures consumed by the frontend tests (vitest).

The frontend re-implements several pieces of the domain's mathematics in TypeScript: the
transforms of :mod:`retina.model.viewport_state`, the MTF of :mod:`retina.model.stf`, and the
two transfer curves the histogram panel draws (PCHIP and GHS). A silent port that drifts is
the worst possible scenario — the image would still be displayed, simply in the wrong place or
with the wrong stretch, without anything breaking.

Hence these fixtures: the reference values are produced **by the domain itself**, then compared
on the TS side. An early prototype had already validated the principle (48/48 identical
values); here we freeze it into a permanent test.

    .venv\\Scripts\\python.exe scripts/gen_web_fixtures.py

The generated file is **versioned**: regenerating it must be a deliberate act, visible in
review, not a side effect of running the tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from retina.model.image import Image
from retina.model.stf import ChannelSTF
from retina.model.viewport_state import ViewportState

OUT = Path(__file__).resolve().parents[1] / "web" / "tests" / "fixtures"

#: Control points: corners, an unaligned interior point, and one **outside the frame** — that
#: is where sign or frame-of-reference mistakes show up, not at the center.
POINTS = [(0.0, 0.0), (1200.0, 800.0), (123.5, 456.75), (-40.0, 12.0), (600.0, 400.0)]

#: (zoom, center) — 1:1, heavy minification, magnification with an off-center view.
CASES = [
    (1.0, None),
    (0.25, None),
    (4.0, (1234.5, 678.25)),
    (0.125, (0.0, 0.0)),
]

IMAGE_SIZE = (1200, 800)
VIEWPORT = (1920.0, 1080.0)


def transforms() -> dict:
    state = ViewportState(IMAGE_SIZE)
    state.set_geometry(*VIEWPORT, 1.0)
    cases = []
    for zoom, center in CASES:
        state.set_zoom(zoom)
        state.set_center(center or (IMAGE_SIZE[0] / 2.0, IMAGE_SIZE[1] / 2.0))
        cases.append(
            {
                "zoom": state.zoom,
                "center": list(state.center),
                "vw": state.vw,
                "vh": state.vh,
                "points": [list(p) for p in POINTS],
                "image_to_viewport": [list(state.image_to_viewport(p)) for p in POINTS],
                "viewport_to_image": [list(state.viewport_to_image(p)) for p in POINTS],
            }
        )
    return {"image_size": list(IMAGE_SIZE), "cases": cases}


def zoom_pivot() -> dict:
    """Pivot zoom is the easiest formula to get wrong: it gets its own set of cases."""
    cases = []
    for start, target, pivot in ((1.0, 2.0, (300.0, 200.0)), (2.0, 0.5, (900.0, 700.0))):
        state = ViewportState(IMAGE_SIZE)
        state.set_geometry(*VIEWPORT, 1.0)
        state.set_zoom(start)
        state.set_center((IMAGE_SIZE[0] / 2.0, IMAGE_SIZE[1] / 2.0))
        state.set_zoom(target, pivot)
        cases.append(
            {
                "start_zoom": start,
                "target_zoom": target,
                "pivot": list(pivot),
                "center_before": [IMAGE_SIZE[0] / 2.0, IMAGE_SIZE[1] / 2.0],
                "center_after": list(state.center),
            }
        )
    return {"image_size": list(IMAGE_SIZE), "vw": VIEWPORT[0], "vh": VIEWPORT[1], "cases": cases}


def stf() -> dict:
    """Expected STF output, densely sampled in the shadows.

    That is where the MTF of an auto-stretch is nearly vertical, hence where an approximate
    port gives itself away. The parameters come from a real ``compute_auto_stretch`` on a
    synthetic sky background, not from values picked by hand.
    """
    rng = np.random.default_rng(20260725)
    yy = np.linspace(0.0, 1.0, 200, dtype=np.float32)[:, None]
    data = (0.0015 + 0.0008 * yy + rng.normal(0, 2e-4, (200, 200)).astype(np.float32))[:, :, None]
    data = np.repeat(np.clip(data, 0.0, 1.0), 3, axis=2)
    auto = Image(np.ascontiguousarray(data)).compute_auto_stretch()

    raw = np.concatenate(
        [
            np.linspace(0.0, 0.02, 40, dtype=np.float32),
            np.linspace(0.02, 1.0, 40, dtype=np.float32),
        ]
    )
    channels = [
        {
            "shadows": float(c.shadows),
            "midtones": float(c.midtones),
            "highlights": float(c.highlights),
            "expected": [float(v) for v in c.apply(raw)],
        }
        for c in auto.channels
    ]
    edge = [
        {"midtones": m, "expected": [float(v) for v in ChannelSTF(midtones=m).apply(raw)]}
        for m in (0.0, 0.5, 1.0)
    ]
    return {"raw": [float(v) for v in raw], "channels": channels, "edge_cases": edge}


def pchip() -> dict:
    """Expected output of the PCHIP interpolation of ``processes/curves.py``.

    The curve editor re-implements it in TypeScript to draw what the computation will do. A
    divergence would break nothing visible: the displayed curve would simply stop matching the
    result, which is worse than an outright error.
    """
    from retina.processes.curves import _pchip

    cases = [
        [[0.0, 0.0], [1.0, 1.0]],                                     # identity
        [[0.0, 0.0], [0.25, 0.5], [0.75, 0.6], [1.0, 1.0]],           # gentle S-curve
        [[0.0, 0.2], [0.5, 0.2], [1.0, 0.9]],                         # plateau then rise
        [[0.0, 0.0], [0.1, 0.8], [0.2, 0.1], [1.0, 1.0]],             # extrema: bounded monotony
    ]
    x = np.linspace(0.0, 1.0, 101, dtype=np.float64)
    return {
        "x": [float(v) for v in x],
        "cases": [
            {
                "points": points,
                "expected": [
                    float(v)
                    for v in _pchip(
                        np.array([p[0] for p in points]),
                        np.array([p[1] for p in points]),
                        x,
                    )
                ],
            }
            for points in cases
        ],
    }


def ghs() -> dict:
    """Expected output of ``processes/stretch.py::ghs_transfer``.

    The histogram panel re-implements this curve in TypeScript to draw it. The cases cover the
    **five sub-families** (b = −1, b < 0, b = 0, b = 1, b > 0), the LP/HP protection segments
    and the inverse form: those are the places where the formulas change, hence the places
    where a port drifts.
    """
    from retina.processes.stretch import ghs_transfer

    cases = [
        # (factor, b, SP, LP, HP, inverse)
        (0.0, 0.0, 0.2, 0.0, 1.0, False),      # zero factor: identity
        (3.0, -1.0, 0.1, 0.0, 1.0, False),     # logarithmic
        (3.0, -0.5, 0.1, 0.0, 1.0, False),     # integral
        (3.0, 0.0, 0.1, 0.0, 1.0, False),      # exponential
        (3.0, 1.0, 0.1, 0.0, 1.0, False),      # harmonic
        (2.0, 8.0, 0.25, 0.0, 1.0, False),     # hyperbolic
        (2.5, 6.0, 0.15, 0.05, 0.85, False),   # both protection segments
        (2.5, 6.0, 0.15, 0.05, 0.85, True),    # its inverse form
        (1.5, -3.0, 0.4, 0.1, 0.9, False),     # strongly negative b, SP in the middle
    ]
    x = np.linspace(0.0, 1.0, 101, dtype=np.float64)
    return {
        "x": [float(v) for v in x],
        "cases": [
            {
                "stretch_factor": sf, "local_intensity": b, "symmetry_point": sp,
                "protect_shadows": lp, "protect_highlights": hp, "invert": inv,
                "expected": [float(v) for v in ghs_transfer(x, sf, b, sp, lp, hp, inverse=inv)],
            }
            for sf, b, sp, lp, hp, inv in cases
        ],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "transforms.json": transforms(),
        "zoom-pivot.json": zoom_pivot(),
        "stf.json": stf(),
        "pchip.json": pchip(),
        "ghs.json": ghs(),
    }
    for name, payload in fixtures.items():
        path = OUT / name
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"[fixtures] {path.relative_to(OUT.parents[2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
