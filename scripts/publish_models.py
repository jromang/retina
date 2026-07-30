#!/usr/bin/env python3
"""Publish the AI-model mirror on Hugging Face, and regenerate the manifest.

A **deliberate** act, like ``fetch_spectra.py``: nothing runs it on its own, and its output
(``resources/models/manifest.json``) is versioned.

# What it does, and why it exists

Retina cannot embed the GraXpert models — the smallest one weighs 218 MB, GitHub refuses a
blob over 100 MB and PyPI a wheel file over 100 MB. So we **re-host** them on
``huggingface.co/jromanghf/graxpert-models``, whose LFS copes with the gigabyte, and the
manifest points there. This script is the chain that fills that mirror:

1. fetches the models through **GraXpert's own downloader** — its code, its client, its keys
   (they ship in the PyPI package). It is GraXpert that authenticates against its own object
   store, doing exactly what it is built to do; we never touch its keys;
2. extracts every ``model.onnx`` and computes its SHA-256;
3. writes a **model card** carrying the CC BY-NC-SA attribution (a condition of the licence)
   along with GraXpert's original licence files, then pushes the lot to HF;
4. rewrites ``resources/models/manifest.json`` with the ``resolve`` URLs, the digests and the
   licences.

# Why we are allowed to

GraXpert's **code** is GPL-3, but its **models** are under CC BY-NC-SA 4.0
(``licenses/*-Model-LICENSE.html`` in their repository), which explicitly permits
redistribution with attribution, under the same terms, with no added restriction. We
redistribute **unchanged** (digests as evidence), we attribute, and we show the ban on
**commercial** use to the user (HF card, ``retina.credits``, process documentation). What we
do **not** do: extract the keys to hit their bucket ourselves — GraXpert is the one that
downloads, with its own.

Usage:
    pip install --no-deps graxpert && pip install minio appdirs packaging  # in a throwaway venv
    hf auth login                                                          # write token
    python scripts/publish_models.py                    # publish + rewrite the manifest
    python scripts/publish_models.py --manifest-only    # rewrite the manifest, push nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "python" / "retina" / "resources" / "models" / "manifest.json"

REPO = "jromanghf/graxpert-models"
HF_BASE = f"https://huggingface.co/{REPO}/resolve/main"
HF_HOME = f"https://huggingface.co/{REPO}"

#: (Retina task, GraXpert bucket, version). The latest versions seen; to be updated whenever
#: GraXpert publishes new ones (``list_remote_versions`` lists them).
MODELS = [
    ("denoise",        "graxpert-denoise-ai-onnx",                "3.0.2"),
    ("background",     "graxpert-bge-ai-onnx",                    "1.0.1"),
    ("deconv_object",  "graxpert-deconvolution-object-ai-onnx",   "1.0.1"),
    ("deconv_stellar", "graxpert-deconvolution-stars-ai-onnx",    "1.0.0"),
]

#: GraXpert licence files to ship alongside the mirror (verbatim attribution)
GRAXPERT_LICENSES = (
    "BGE-Model-LICENSE.html",
    "Denoise-Model-LICENSE.html",
    "Deconvolution-Model-LICENSE.html",
)

NAMES = {
    "denoise": "GraXpert denoise",
    "background": "GraXpert background extraction",
    "deconv_object": "GraXpert deconvolution (object)",
    "deconv_stellar": "GraXpert deconvolution (stellar)",
}


def _fetch_models(dest: Path) -> list[dict]:
    """Download and extract the models through the GraXpert client. Return their metadata."""
    import graxpert.ai_model_handling  # noqa: F401 — checks that the package is present
    from graxpert.s3_secrets import endpoint, ro_access_key, ro_secret_key
    from minio import Minio

    client = Minio(endpoint, ro_access_key, ro_secret_key)
    dest.mkdir(parents=True, exist_ok=True)
    harvest = []
    for task, bucket, version in MODELS:
        zpath = dest / f"{task}-{version}.zip"
        print(f"[models] {task} {version} ← {bucket}", flush=True)
        client.fget_object(bucket, f"model-{version}.zip", str(zpath))
        key = task.replace("_", "-")
        target = dest / f"graxpert-{key}-{version}.onnx"
        with zipfile.ZipFile(zpath) as z:
            name = next(n for n in z.namelist() if n.endswith("model.onnx"))
            target.write_bytes(z.read(name))
        zpath.unlink()
        digest = hashlib.sha256()
        with open(target, "rb") as f:
            while block := f.read(1 << 20):
                digest.update(block)
        harvest.append({"task": task, "version": version, "file": target.name,
                        "sha256": digest.hexdigest(), "size": target.stat().st_size})
    return harvest


def _model_card(harvest: list[dict]) -> str:
    by_task = {m["task"]: m for m in harvest}

    def line(task: str, title: str) -> str:
        m = by_task[task]
        return (f"| `{m['file']}` | {title} | {m['version']} | "
                f"{m['size'] / 1e6:.0f} MB | `{m['sha256'][:16]}…` |")

    return f"""---
license: cc-by-nc-sa-4.0
tags:
  - astrophotography
  - image-restoration
  - onnx
  - graxpert
library_name: onnx
---

# GraXpert models — mirror for Retina

Redistribution mirror of the neural-network models produced by
[GraXpert](https://github.com/Steffenhir/GraXpert), so that
[Retina](https://github.com/jromang/retina2) can fetch them without a full GraXpert install.

**These models are not ours.** They are the work of the **GraXpert Development Team and its
contributors**, licensed under **CC BY-NC-SA 4.0** — distinct from the GPL-3 of the GraXpert
code. Files here are **unmodified**; SHA-256 sums below let anyone verify that.

## ⚠️ NonCommercial

CC BY-NC-SA 4.0 forbids **commercial use**. These models may be used for non-commercial
purposes only. This restriction comes from GraXpert, not from Retina, which places no such
limit. Redistribution is permitted (this mirror relies on it) with attribution, same licence,
no added restrictions.

## Attribution

- **Authors:** GraXpert Development Team and contributors.
- **Source:** <https://github.com/Steffenhir/GraXpert>
- **Full licences and contributor lists** (verbatim) in `licenses/`.
- **Changes:** none.

## Models

| File | Task | Version | Size | SHA-256 |
|---|---|---|---|---|
{line("denoise", "Denoising")}
{line("background", "Background extraction")}
{line("deconv_object", "Deconvolution — extended object")}
{line("deconv_stellar", "Deconvolution — stellar")}

## How Retina uses them

Retina prefers a local GraXpert install if it finds one (models discovered and used in place);
this mirror is the fallback. Either way, the model used — name, version, SHA-256 — is written
into the processing history and the FITS keywords.

If you are a GraXpert maintainer and would rather this mirror not exist, or would prefer to host
it yourself, please open a discussion here.
"""


def _upload(work: Path, harvest: list[dict]) -> None:
    (work / "README.md").write_text(_model_card(harvest), encoding="utf-8")
    licenses = work / "licenses"
    licenses.mkdir(exist_ok=True)
    base = "https://raw.githubusercontent.com/Steffenhir/GraXpert/main/licenses/"
    for name in GRAXPERT_LICENSES:
        request = urllib.request.Request(base + name, headers={"User-Agent": "retina"})
        with urllib.request.urlopen(request, timeout=30) as stream:
            (licenses / name).write_bytes(stream.read())
    print(f"[models] push → {REPO}", flush=True)
    subprocess.run(
        ["hf", "upload", REPO, str(work), ".", "--repo-type", "model",
         "--commit-message", "GraXpert models (CC BY-NC-SA 4.0), unmodified mirror for Retina"],
        check=True)


def _write_manifest(harvest: list[dict]) -> None:
    by_task = {m["task"]: m for m in harvest}
    models = []
    for task, _, _ in MODELS:
        m = by_task[task]
        key = task.replace("_", "-")
        models.append({
            "id": f"graxpert-{key}-{m['version']}", "task": task, "name": NAMES[task],
            "version": m["version"], "url": f"{HF_BASE}/{m['file']}",
            "sha256": m["sha256"], "size": m["size"], "license": "CC-BY-NC-SA-4.0",
            "homepage": HF_HOME,
        })
    manifest = {
        "schema": 1,
        "comment": [
            "Catalog of downloadable AI models. See retina/ai/models.py.",
            "Regenerated by scripts/publish_models.py (a deliberate act).",
            "GraXpert models (https://github.com/Steffenhir/GraXpert), redistributed UNCHANGED",
            f"from {HF_HOME}. Under CC BY-NC-SA 4.0: COMMERCIAL use forbidden (a restriction",
            "from GraXpert, not from Retina). discover_local() takes precedence over these.",
        ],
        "models": models,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"[models] manifest rewritten: {MANIFEST.relative_to(ROOT)} ({len(models)} models)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-only", action="store_true",
                         help="rewrite the manifest from the models already online, without "
                              "downloading or pushing anything (digests read from the mirror)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.manifest_only:
        # Recompute the digests from the online mirror, without going through GraXpert again.
        harvest = []
        for task, _, version in MODELS:
            key = task.replace("_", "-")
            file = f"graxpert-{key}-{version}.onnx"
            url = f"{HF_BASE}/{file}"
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "retina"})) as stream:
                while block := stream.read(1 << 20):
                    digest.update(block)
                    size += len(block)
            harvest.append({"task": task, "version": version, "file": file,
                            "sha256": digest.hexdigest(), "size": size})
        _write_manifest(harvest)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        harvest = _fetch_models(work)
        _upload(work, harvest)
        _write_manifest(harvest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
