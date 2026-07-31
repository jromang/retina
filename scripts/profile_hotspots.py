"""Profiling of the candidates for a Rust port / a GPU conversion (see ARCHITECTURE.md).

Rust only targets **measured** hot spots: this script is the measurement, and its report is
the evidence to produce before any port. For each candidate it times (3 runs, min) and
profiles (cProfile) one execution on a realistic synthetic image, then splits the time between
**Python code of the retina package** and **C extensions** (scipy/skimage/numpy).

Decision criteria, applied to the report:

- **GO for a Rust port**: > ~2 s at 24 Mpx AND most (> 70 %) of the cumulated time in Python
  frames of ``retina/`` — loops a native multicore core can swallow.
- **NO-GO**             : the time already sits in C (scipy/skimage/PyWavelets) — Rust would
  only bring a risky rewrite of the same native code.
- **GPU candidate (xp)**: Rust NO-GO but the operator is expressible in ufuncs/ndimage — the
  CuPy conversion is then the lever (cf. retina/backend/xp.py).

Usage:

    python scripts/profile_hotspots.py            # 24 Mpx (slow but faithful)
    python scripts/profile_hotspots.py --mpx 6    # 6 Mpx, times extrapolated ×4 (fast)
    python scripts/profile_hotspots.py --gpu      # CPU vs GPU of the ported candidates
    python scripts/profile_hotspots.py --gpu --threshold   # size curve → GPU_MIN_PIXELS

Since the candidates are linear in pixel count (full-frame iterations), measuring at 6 Mpx and
extrapolating ×4 is a good proxy — the report says when it extrapolates. Write the conclusions
down (GO as well as NO-GO) so that nobody profiles the same candidate twice.

# Measuring a GPU without fooling yourself (``--gpu`` mode)

Three precautions, without which the numbers are wrong rather than merely imprecise:

- **Synchronize.** CuPy launches are asynchronous: a bare ``perf_counter`` times the
  submission of the commands, not the computation. ``xp.synchronize()`` brackets every run.
- **Transfers included.** We measure what the user waits for, and ``_apply`` starts from a
  numpy array to come back to one: the PCIe round trip is part of the time. A separate column
  gives its cost, so that one can see it is negligible.
- **The CPU measured with the GPU switched off.** ``RETINA_GPU=0`` is set around the host
  runs, otherwise the "CPU reference" of a ported candidate would be… the GPU.

The first run absorbs the JIT compilation of the kernels and the creation of the cuFFT plans:
taking the min of three runs discards it, just as for the CPU.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import time

import numpy as np
from _console import configure as _configure_console


def make_field(mpx: float, channels: int = 1, seed: int = 7) -> np.ndarray:
    """Realistic synthetic field: background + gradient + Gaussian stars + noise."""
    aspect = 1.5
    height = int(np.sqrt(mpx * 1e6 / aspect))
    width = int(height * aspect)
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    background = 0.02 + 0.01 * (x / width) + 0.008 * (y / height)
    image = np.tile(background[:, :, None], (1, 1, channels))
    for _ in range(200):
        cx, cy = rng.uniform(0, width), rng.uniform(0, height)
        flux, s = rng.uniform(0.1, 0.9), rng.uniform(1.2, 3.0)
        y0, y1 = max(0, int(cy - 12)), min(height, int(cy + 12))
        x0, x1 = max(0, int(cx - 12)), min(width, int(cx + 12))
        if y1 <= y0 or x1 <= x0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        star = flux * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s)))
        image[y0:y1, x0:x1] += star[:, :, None]
    image += rng.normal(0.0, 0.003, image.shape).astype(np.float32)
    return np.clip(image, 0.0, 1.0).astype(np.float32)


def candidates() -> list[tuple[str, object]]:
    """(name, configured process) — parameters typical of a real session."""
    from retina.process.registry import all_processes

    get = all_processes().__getitem__
    return [
        ("GaussianConvolution (Rust yardstick)", get("GaussianConvolution")(sigma=2.5)),
        ("Deconvolution RL ×20", get("Deconvolution")(iterations=20)),
        ("NoiseReduction tv", get("NoiseReduction")(method="tv")),
        ("NoiseReduction wavelet", get("NoiseReduction")(method="wavelet")),
        ("NoiseReduction bilateral", get("NoiseReduction")(method="bilateral")),
        ("TGVDenoise ×100", get("TGVDenoise")(iterations=100)),
        ("ACDNR", get("ACDNR")()),
        ("NonLocalMeansDenoise", get("NonLocalMeansDenoise")()),
        ("MultiscaleLinearTransform", get("MultiscaleLinearTransform")()),
        ("GradientHDRCompression", get("GradientHDRCompression")()),
    ]


def profile_one(process, image, runs: int = 3) -> tuple[float, float, str]:
    """(best time, retina-Python share of the cumtime, readable top 5)."""
    from retina.model.image import Image

    best = float("inf")
    for _ in range(runs):
        img = Image(image.copy())
        start = time.perf_counter()
        process.execute_on_image(img)
        best = min(best, time.perf_counter() - start)

    profiler = cProfile.Profile()
    img = Image(image.copy())
    profiler.enable()
    process.execute_on_image(img)
    profiler.disable()

    stats = pstats.Stats(profiler)
    total = sum(entry[2] for entry in stats.stats.values())  # cumulated tottime
    # "retina Python" = .py frames of the retina/ package OUTSIDE site-packages (the repo's
    # venv carries "retina2" in its path, so a plain `in` would match scipy and skimage) —
    # plus the numpy ufuncs they orchestrate (method 'reduce', numpy <built-in> functions
    # called from our frames count as C).
    def is_retina_py(key) -> bool:
        path = key[0] or ""
        return (path.endswith(".py") and "/retina/" in path.replace("\\", "/")
                and "site-packages" not in path)

    retina_py = sum(entry[2] for key, entry in stats.stats.items() if is_retina_py(key))
    stream = io.StringIO()
    stats.stream = stream
    stats.sort_stats("tottime").print_stats(5)
    return best, (retina_py / total if total > 0 else 0.0), stream.getvalue()


#: Candidates actually ported to the GPU — the ones `--gpu` compares.
GPU_CANDIDATES = ("Deconvolution RL ×20", "NoiseReduction tv", "TGVDenoise ×100")


def _time_best(action, runs: int = 3) -> float:
    """Best of ``runs``, **synchronized** on both sides.

    Without the synchronization we would be timing the submission of the commands to the GPU
    instead of the computation, and everything would look instantaneous.
    """
    from retina.backend import xp

    best = float("inf")
    for _ in range(runs):
        xp.synchronize()
        start = time.perf_counter()
        action()
        xp.synchronize()
        best = min(best, time.perf_counter() - start)
    return best


def _with_gpu_disabled(action):
    """Run ``action`` with the GPU switched off — that is how one gets a true CPU reference."""
    import os

    previous = os.environ.get("RETINA_GPU")
    os.environ["RETINA_GPU"] = "0"
    try:
        return action()
    finally:
        if previous is None:
            os.environ.pop("RETINA_GPU", None)
        else:
            os.environ["RETINA_GPU"] = previous


def gpu_report(mpx: float) -> None:
    """CPU / GPU table of the ported candidates, transfers included."""
    from retina.backend import xp
    from retina.model.image import Image

    if not xp.gpu_available():
        print("No CuPy GPU available — nothing to measure.")
        return
    image = make_field(mpx)
    height, width = image.shape[:2]
    print(f"# CPU vs GPU — image {width}×{height} ({mpx:g} Mpx), transfers included")
    print(f"  upload threshold: GPU_MIN_PIXELS = {xp.GPU_MIN_PIXELS:,}".replace(",", " "))
    print()

    round_trip = _time_best(lambda: xp.to_numpy(xp.to_device(image, min_pixels=0)))
    print(f"  PCIe round trip of the test image: {round_trip * 1000:.0f} ms")
    print()
    print("| Candidate | CPU (s) | GPU (s) | speed-up |")
    print("|---|---|---|---|")
    for name, process in candidates():
        if name not in GPU_CANDIDATES:
            continue
        try:
            cpu = _with_gpu_disabled(
                lambda p=process: _time_best(lambda: p.execute_on_image(Image(image.copy())))
            )
            gpu = _time_best(lambda p=process: p.execute_on_image(Image(image.copy())))
        except Exception as exc:
            print(f"| {name} | — | — | error: {exc} |")
            continue
        print(f"| {name} | {cpu:.2f} | {gpu:.2f} | ×{cpu / gpu:.1f} |")


def ratio_threshold() -> None:
    """Speed-up as a function of size — this curve is what sets ``GPU_MIN_PIXELS``."""
    from retina.backend import xp
    from retina.model.image import Image
    from retina.process.registry import all_processes

    if not xp.gpu_available():
        print("No CuPy GPU available — nothing to measure.")
        return
    process = all_processes()["Deconvolution"](iterations=20)
    print("# Speed-up by size (Deconvolution RL ×20) — where the GPU starts to pay off")
    print()
    print("| Mpx | pixels | CPU (s) | GPU (s) | speed-up |")
    print("|---|---|---|---|---|")
    for mpx in (0.25, 0.5, 1.0, 2.0, 4.0, 12.0, 24.0):
        image = make_field(mpx)
        pixels = image.shape[0] * image.shape[1]
        def one_pass(img=image):
            return process.execute_on_image(Image(img.copy()))

        cpu = _with_gpu_disabled(lambda: _time_best(one_pass))
        # Threshold forced to zero: we want the curve, not the effect of the very threshold
        # we are trying to set.
        previous = xp.GPU_MIN_PIXELS
        xp.GPU_MIN_PIXELS = 0
        try:
            gpu = _time_best(one_pass)
        finally:
            xp.GPU_MIN_PIXELS = previous
        print(f"| {mpx:g} | {pixels:,} | {cpu:.3f} | {gpu:.3f} | ×{cpu / gpu:.1f} |"
              .replace(",", " "))


def main() -> None:
    _configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mpx", type=float, default=24.0,
                        help="size of the test image in megapixels (default 24)")
    parser.add_argument("--verbose", action="store_true", help="print the cProfile top 5")
    parser.add_argument("--gpu", action="store_true",
                        help="compare CPU and GPU on the ported candidates")
    parser.add_argument("--threshold", action="store_true",
                        help="with --gpu: speed-up curve by size (sets GPU_MIN_PIXELS)")
    args = parser.parse_args()

    if args.gpu:
        if args.threshold:
            ratio_threshold()
        else:
            gpu_report(args.mpx)
        return

    factor = 24.0 / args.mpx
    image = make_field(args.mpx)
    height, width = image.shape[:2]
    print(f"# Hot-spot profile — image {width}×{height} ({args.mpx:g} Mpx)")
    if factor != 1.0:
        print(f"  (times extrapolated ×{factor:.1f} to 24 Mpx — candidates linear in pixels)")
    print()
    print("| Candidate | t (s) | t@24 Mpx | % retina-Python | Verdict |")
    print("|---|---|---|---|---|")
    for name, process in candidates():
        try:
            best, share, top = profile_one(process, image)
        except Exception as exc:
            print(f"| {name} | — | — | — | error: {exc} |")
            continue
        extrapolated = best * factor
        if extrapolated > 2.0 and share > 0.7:
            verdict = "**GO Rust**"
        elif extrapolated > 2.0:
            verdict = "slow but already in C → GPU candidate (xp)"
        else:
            verdict = "NO-GO (fast enough)"
        print(f"| {name} | {best:.2f} | {extrapolated:.2f} | {share * 100:.0f}% | {verdict} |")
        if args.verbose:
            print("```\n" + top + "```")


if __name__ == "__main__":
    main()
