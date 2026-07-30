---
id: NewImage
category: Image
title: New Image
brief: Creates a new image window, blank or filled with a uniform value.
keywords: [new image, creation, canvas, blank, fill, test, synthetic]
related: [SimplexNoise, NoiseGenerator, ImageIdentifier, ChannelCombination]
icon: photo
references:
  - "PixInsight — NewImage process reference."
  - "numpy.full — creating an array filled with a constant value."
---

## Summary

`NewImage` creates a **blank image window** (or one filled with a uniform value), without
reading any file. It is the simplest process in the catalogue — the equivalent of a "new
document" — but it plays an important utility role: producing a canvas of chosen dimensions and
channel count, ready to be populated by `PixelMath`, `SimplexNoise`, `NoiseGenerator`, or any
other operation that writes pixels from scratch rather than loading them.

It is a **global process**: it does not apply to an existing view but directly creates a new
window in the application, exactly like `app.new_window(...)` in the console.

## Use cases

- **Create a working canvas** to compose a synthetic image (test patterns, gradients, masks hand-
  drawn via `PixelMath`).
- **Generate a noise canvas** ahead of a `NoiseGenerator` or `SimplexNoise` step.
- **Build a reference image** (uniform range) to validate a pipeline or debug a process (check
  that a transformation leaves a constant range unchanged).
- **Initialize a manual mask** filled with a given value, to be refined pixel by pixel afterward.

## How it works

The process allocates a numpy `float32` array of shape `(height, width, channels)`, entirely
filled with the value `fill`, wraps it in an `Image` object, and registers it as a new
application window via `app.new_window(...)`, with identifier `new_image_id`. No disk read, no
dependency on an active view: the operation is purely generative.

## Mathematics

There is no transform or statistic involved: the resulting image is a **constant function** over
the image plane. For every pixel coordinate $(x, y)$ and every channel $c$:

$$ I(x, y, c) = f, \qquad 0 \le x < W,\; 0 \le y < H,\; 0 \le c < C, $$

where $f$ = `fill`, $W$ = `width`, $H$ = `height` and $C$ = `channels`. The resulting array has
$W \times H \times C$ identical samples, stored in single precision (`float32`), Retina's
standard numeric exchange format.

## Parameters

- **`width`** — *int*, default `256`, range `1`–`100000`. Width of the created image, in pixels.
- **`height`** — *int*, default `256`, range `1`–`100000`. Height of the created image, in pixels.
- **`channels`** — *int*, default `1`, range `1`–`4`. Number of channels (1 = grayscale,
  3 = RGB, 4 = RGB + alpha depending on downstream usage).
- **`fill`** — *real*, default `0.0`, range `0.0`–`1.0`. Uniform fill value applied to every
  pixel and every channel.
- **`new_image_id`** — *str*, default `'new_image'`. Identifier of the created window; if left
  empty, an identifier is assigned automatically by the application.

## Tips & pitfalls

> **Warning** — `width` and `height` accept up to 100,000 pixels per side; an excessive size
> combined with `channels = 4` can allocate tens of gigabytes of RAM. Keep it reasonable for a
> simple test canvas.

- For a starting black canvas, leave `fill` at `0.0` (default); for a white/saturated canvas,
  use `1.0`.
- The result is always single-precision floating point `[0, 1]` — no particular color space
  until an ICC profile is assigned (see `AssignICCProfile`).
- If `new_image_id` matches an identifier already in use, the existing window is not
  overwritten: a separate new window is created with that same logical id.

## See also

- [SimplexNoise](retina-doc://SimplexNoise) — coherent noise generator, useful after `NewImage`.
- [NoiseGenerator](retina-doc://NoiseGenerator) — Gaussian/Poisson noise for tests or simulation.
- [ImageIdentifier](retina-doc://ImageIdentifier) — rename a window afterward.
- [ChannelCombination](retina-doc://ChannelCombination) — assemble channels, including ones from `NewImage`.

## References

- PixInsight — *NewImage* process reference.
- numpy — *numpy.full*, creating an array filled with a constant value.
