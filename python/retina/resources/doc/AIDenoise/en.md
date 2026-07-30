---
id: AIDenoise
category: NoiseReduction
title: AI Denoise
brief: Neural-network denoising, running an ONNX model locally.
keywords: [AI, denoising, neural network, ONNX, GraXpert, traceability]
related: [NoiseReduction, AIDeconvolution, StarRemoval, TGVDenoise]
icon: wand
references:
  - "ONNX Runtime — local model execution, no remote service."
---

## Summary

`AIDenoise` denoises the image with a **neural network** running on your own machine. Nothing
is sent anywhere: the model is a local `.onnx` file, read by onnxruntime.

The image is processed in **overlapping, feathered tiles**, so a 50 Mpx frame can be denoised
without feeding it to the network in one piece. Every tile reports progress and acts as a
cancellation point.

## You have to supply a model first

Retina **ships no models**, and that is not an oversight. No model in this field is linkable:
GraXpert serves its own from a private S3 bucket whose credentials are embedded in its package,
and StarNet's licence allows neither redistribution nor direct linking. Putting unverifiable
URLs into Retina would have produced the kind of failure nobody can diagnose — a download that
breaks on your machine, six months from now.

> **GraXpert's models are under CC BY-NC-SA 4.0** — separate from the GPL-3 of their code.
> Free and shareable, but **commercial** use is forbidden. Retina itself restricts nothing: if
> you sell prints or work on commission, that restriction is between you and GraXpert. The
> **Help → Licences** panel says so.

**In practice, install GraXpert and let it download its models: Retina finds them on its
own.** Its data folders are scanned every time the panel opens, and the models appear in
`model_id` as `graxpert-denoise-<version>`. Nothing is copied — the file is used where it
lies, which avoids duplicating hundreds of megabytes and letting the two copies drift apart at
the next update.

If your installation is not in the standard place (portable build, shared folder), the
`RETINA_GRAXPERT_DIR` environment variable points at it. And `model` still accepts a direct
path to any `.onnx`, whatever its origin.

The `model_id` parameter will name an entry of the built-in catalogue the day that catalogue
holds any; the machinery (SHA-256 verified download, cache under `~/.cache/retina/models/`,
progress and cancellation) is in place and tested.

## Traceability

This is what sets the process apart from a retouching filter. The model actually used is
recorded:

- in the **instance parameters** — hence in the history, the Python echo, recipes and the
  `.retina` project;
- in the window's **FITS keywords**: `AIMODEL` (name or file), `AIMODVER` (version) and
  `AIMODSHA` (truncated fingerprint).

When replaying a recipe, if the model fingerprint no longer matches the recorded one, nothing
is interrupted — but you are **warned**: the result will not be identical, and it is better to
learn that here than by comparing two images.

## Parameters

- **`model`** — *path*. The `.onnx` file to use.
- **`model_id`** — *str*. Identifier of a catalogue model: either `graxpert-denoise-<version>`
  found in a local GraXpert install, or the same downloaded on demand from the Hugging Face
  mirror. Local wins — nothing is re-downloaded if it is already there.
- **`strength`** — *real*, default `1.0`, range `0`–`1`. Doses the effect: at `1` the network
  decides alone, below that a share of the original image is kept.
- **`tile_size`** — *int*, default `256`. Side of the tiles fed to the network.
- **`overlap`** — *int*, default `32`. Overlap, feathered with a linear ramp. Too small and the
  tile seams show.
- **`model_version`**, **`model_sha256`** — *str*, **filled at execution time**. Do not set them
  by hand; they carry the trace of the model used.

## Tips & pitfalls

> **AI denoising applies to linear data**, before stretching, like any other noise reduction.
> After stretching, the network sees a distribution it was never trained on.

- A model trained on RGB receives a mono plane **replicated into three channels**, and the
  output is averaged back. This is transparent, but it does mean a mono frame costs as much
  time as an RGB one.
- Beyond three channels only the first three go through: alpha has no business in a denoising
  network.

## See also

- [NoiseReduction](retina-doc://NoiseReduction) — classical denoising, no model to supply.
- [AIDeconvolution](retina-doc://AIDeconvolution) — network deconvolution, same machinery.
- [StarRemoval](retina-doc://StarRemoval) — star removal, also with an ONNX backend.

## References

- ONNX Runtime — local model execution, no remote service.
