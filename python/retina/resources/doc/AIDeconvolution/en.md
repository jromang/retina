---
id: AIDeconvolution
category: Deconvolution
title: AI Deconvolution
brief: Neural-network deconvolution, extended object or stars, from a local ONNX model.
keywords: [AI, deconvolution, neural network, ONNX, sharpness, traceability]
related: [Deconvolution, AIDenoise, DynamicPSF, StarRemoval]
icon: sparkles
references:
  - "ONNX Runtime — local model execution, no remote service."
---

## Summary

`AIDeconvolution` restores sharpness with a **neural network** running on your own machine.
Unlike [Deconvolution](retina-doc://Deconvolution), which explicitly inverts a measured or
parametric PSF, the network has learned the blurred → sharp relation from a corpus: it asks for
no PSF, but neither does it account for what it does.

The `target` parameter picks the model family: `object` for extended structures (galaxies,
nebulae), `stellar` to tighten stars. These are two distinct networks — swapping them yields
mediocre results, not an error.

The image is processed in **overlapping, feathered tiles**, with per-tile progress and
cancellation.

## You have to supply a model first

Retina **ships no models**: no model in this field is linkable (private S3 bucket for
GraXpert, proprietary licence for StarNet). GraXpert's models are moreover under
**CC BY-NC-SA 4.0** — free, but **commercial use is forbidden**; see **Help → Licences**.
**Install GraXpert and let it download its models: Retina finds them on its own**, and offers
them in `model_id` as `graxpert-deconv-object-<version>` and
`graxpert-deconv-stellar-<version>`. Nothing is copied. A non-standard installation is pointed
at with `RETINA_GRAXPERT_DIR`, and `model` still accepts a direct path.

The built-in catalogue (`model_id`) carries these same models, re-hosted unchanged on
`huggingface.co/jromanghf/graxpert-models` and downloaded on demand, SHA-256 verified. A local
install, if present, takes priority over the download.

## Traceability

The model used is recorded in the **instance parameters** — hence in the history, the Python
echo, recipes and the `.retina` project — and in the window's **FITS keywords** (`AIMODEL`,
`AIMODVER`, `AIMODSHA`). On replay, a fingerprint that no longer matches interrupts nothing but
warns you.

This is the concrete answer to the charge levelled at these tools: not "trust us", but *here is
which file, of which fingerprint, produced these pixels*.

## Parameters

- **`target`** — *enum* `object` | `stellar`, default `object`. Model family.
- **`model`** — *path*. The `.onnx` file to use.
- **`model_id`** — *str*. Identifier of a catalogue model: `graxpert-deconv-object-<version>`
  or `graxpert-deconv-stellar-<version>`, local (GraXpert install) or downloaded from the HF mirror.
- **`strength`** — *real*, default `1.0`, range `0`–`1`. Doses the effect.
- **`tile_size`** — *int*, default `256`. **`overlap`** — *int*, default `32`.
- **`model_version`**, **`model_sha256`** — *str*, **filled at execution time**.

## Tips & pitfalls

> **On linear data**, before stretching — like classical deconvolution.

- A network does not conserve flux: unlike Richardson-Lucy, nothing guarantees your stars keep
  their photometry. For photometric work, prefer
  [Deconvolution](retina-doc://Deconvolution).
- Applying an `object` model to a dense star field raises no error; it simply produces a poor
  result. Check `target`.

## See also

- [Deconvolution](retina-doc://Deconvolution) — regularized Richardson-Lucy, measured or
  parametric PSF, flux conserving.
- [AIDenoise](retina-doc://AIDenoise) — network denoising, same machinery.
- [DynamicPSF](retina-doc://DynamicPSF) — PSF measurement, if you prefer the explicit route.

## References

- ONNX Runtime — local model execution, no remote service.
