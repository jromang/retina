"""Total-variation denoising — written in "xp", hence CPU **and** GPU from the same code.

Why rewrite it rather than call `skimage.restoration.denoise_tv_chambolle`: the latter is pure
numpy and has no CuPy counterpart. The off-the-shelf paths cost more than they returned —
`cucim` is an entire RAPIDS dependency, Linux only, for one function — whereas Chambolle's
algorithm (2004) fits in thirty lines of gradients and projections, exactly the primitives the
repository's TGV loop already uses (`processes/denoise.py`).

**One code path, not two.** This version replaces skimage on the CPU side as well: keeping
skimage on the host and ours on the GPU would let two implementations diverge, and the day
they no longer returned the same thing nobody would know which to believe. The counterpart is
a parity test against skimage, which is the fair price.

The stopping criterion is taken as is, including its test on every iteration — which costs one
synchronization per pass on GPU. That is accepted: changing its cadence would make the number
of iterations diverge between host and device, hence the results, in order to save a cost that
is negligible next to the work of one pass on a large image.
"""

from __future__ import annotations

from .xp import get_array_module


def _tv_chambolle_nd(image, weight: float, eps: float, max_num_iter: int):
    """Core of the algorithm, on an n-dimensional array, with no channel axis."""
    xp = get_array_module(image)
    ndim = image.ndim
    p = xp.zeros((ndim, *image.shape), dtype=image.dtype)
    g = xp.zeros_like(p)
    d = xp.zeros_like(image)
    out = image
    energie_initiale = previous_energy = None

    for tour in range(int(max_num_iter)):
        if tour > 0:
            # `d` is the (negative) divergence of p: the sum of the backward differences.
            d = -p.sum(0)
            for axis in range(ndim):
                tranche_d = [slice(None)] * ndim
                tranche_p = [slice(None)] * (ndim + 1)
                tranche_d[axis] = slice(1, None)
                tranche_p[axis + 1] = slice(0, -1)
                tranche_p[0] = axis
                d[tuple(tranche_d)] += p[tuple(tranche_p)]
            out = image + d
        energy = (d ** 2).sum()

        for axis in range(ndim):
            tranche_g = [slice(None)] * (ndim + 1)
            tranche_g[axis + 1] = slice(0, -1)
            tranche_g[0] = axis
            g[tuple(tranche_g)] = xp.diff(out, axis=axis)

        norm = xp.sqrt((g ** 2).sum(axis=0))[xp.newaxis, ...]
        energy = energy + weight * norm.sum()
        tau = 1.0 / (2.0 * ndim)
        norm = norm * (tau / weight) + 1.0
        p -= tau * g
        p /= norm
        energy = float(energy) / float(image.size)

        if tour == 0:
            energie_initiale = previous_energy = energy
        elif abs(previous_energy - energy) < eps * energie_initiale:
            break
        else:
            previous_energy = energy
    return out


def tv_chambolle(image, weight: float = 0.1, *, eps: float = 2.0e-4,
                 max_num_iter: int = 200, channel_axis: int | None = None):
    """Total-variation denoising (Rudin-Osher-Fatemi, Chambolle's algorithm).

    ``image`` is a numpy **or** CuPy array: the dispatch follows its type, and the output lives
    where the input lives. ``channel_axis`` processes each channel separately, as the reference
    implementation does — a vectorial TV would couple the channels and return something else.
    """
    xp = get_array_module(image)
    if channel_axis is None:
        return _tv_chambolle_nd(image, float(weight), float(eps), int(max_num_iter))
    axis = int(channel_axis) % image.ndim
    output = xp.zeros_like(image)
    for c in range(image.shape[axis]):
        index = [slice(None)] * image.ndim
        index[axis] = c
        key = tuple(index)
        output[key] = _tv_chambolle_nd(image[key], float(weight), float(eps),
                                       int(max_num_iter))
    return output
