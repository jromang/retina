"""XISF I/O (the native format) through the PyPI ``xisf`` library.

XISF is an open spec (XML header + binary blocks; compression, checksums, typed properties,
FITS keywords, ICC, CFA, embedded STF). The round trip covers what the library can do:

- **FITS keywords** (``FITSKeywords``), read and written — the same contract as
  ``load_fits``;
- **compression** on write (``zlib``/``lz4``/``lz4hc``/``zstd`` + byte-shuffle), defaulting
  to shuffled ``lz4hc`` — the PixInsight default, fast to decode; the library reads every
  standard codec, so compressed PixInsight files open;
- **embedded STF**: the ``Retina:DisplayFunction`` property (F32Matrix C×3, one
  ``[shadows, midtones, highlights]`` row per channel — our :mod:`retina.model.stf` model).
  A property of ours, cleanly ignored by other readers.

- **checksums** of the attached blocks, written and verified (:func:`verify_checksums`). The
  library does not know about them; they are set by re-reading the header after the write,
  which avoids writing a homemade XISF writer for an integrity annotation.

**Documented limits** (the library does not offer them — "do not reinvent" rule: no homemade
XISF writer): the **ICC** profile, the **CFA** and the core
``DisplayFunction``/``Resolution``/``Thumbnail`` elements are neither written nor parsed.
Candidates for an upstream contribution.
The library's API is encapsulated here so it can be swapped without affecting the rest.
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET

import numpy as np

from ..i18n import translate as _t
from ..model.image import Image

#: id of the XISF property carrying the STF (one row per channel: s, m, h)
STF_PROPERTY = "Retina:DisplayFunction"

# --- XISF 1.0 monolithic structure ---------------------------------------------------
# signature (8) + header length uint32 LE (4) + reserved field (4), then the XML header,
# an alignment padding, and the attached blocks.
_SIGNATURE = b"XISF0100"
_HEADER_LEN_SIZE = 4
_RESERVED_SIZE = 4
_HEADER_OFFSET = len(_SIGNATURE) + _HEADER_LEN_SIZE + _RESERVED_SIZE
_ALIGN = 4096  # block alignment used by the library (XISF._block_alignment_size)
_XISF_NS = "http://www.pixinsight.com/xisf"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

#: checksum algorithms of the XISF 1.0 spec, with their attribute identifier.
CHECKSUM_ALGORITHMS = {"sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}

#: algorithm used by default on write. PixInsight writes none by default; we write one,
#: because an integration master read back six months later must be able to say whether it
#: has rotted on disk. The cost is one hash of the compressed block.
DEFAULT_CHECKSUM = "sha256"


def _require_xisf():
    try:
        import xisf  # type: ignore

        return xisf
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            _t("XISF support requires the 'xisf' package (pip install 'retina[xisf]').")
        ) from exc


def _retype(raw: str):
    """Re-type a FITS keyword value (the library returns them as raw strings).

    The same logic as the FITS header in reverse: ``T``/``F`` booleans, integer, float,
    otherwise string. The pipeline compares ``GAIN``/``EXPTIME`` numerically — a ``"120.0"``
    left as a string would break the grouping.
    """
    text = raw.strip()
    if text == "T":
        return True
    if text == "F":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


# --- checksums ------------------------------------------------------------------------
def _read_raw_header(f) -> tuple[int, bytes]:
    """Read the header's ``(declared length, XML)``. The null padding is stripped."""
    f.seek(0)
    if f.read(len(_SIGNATURE)) != _SIGNATURE:
        raise ValueError(_t("Missing XISF signature: not a monolithic XISF file."))
    length = int.from_bytes(f.read(_HEADER_LEN_SIZE), "little")
    f.seek(_RESERVED_SIZE, os.SEEK_CUR)
    return length, f.read(length).rstrip(b"\0")


def _attached_blocks(root) -> list[tuple[ET.Element, int, int]]:
    """``(element, position, size)`` of every block with an ``attachment`` location.

    *Inline* and *embedded* blocks carry their bytes inside the header itself: signing them
    would amount to signing the header, which contains the signature.
    """
    found = []
    for elem in root.iter():
        location = elem.get("location", "")
        if location.startswith("attachment:"):
            _, position, size = location.split(":")[:3]
            found.append((elem, int(position), int(size)))
    return found


def _digest(f, position: int, size: int, algorithm: str) -> str:
    """Digest of the bytes **as stored** — therefore compressed if the block is.

    That is the order of the reference reader, which verifies before decompressing: a
    corrupted block must be detected without having to go through a decompressor it would
    make fail in an obscure way.
    """
    digest = CHECKSUM_ALGORITHMS[algorithm]()
    f.seek(position)
    remaining = size
    while remaining > 0:
        chunk = f.read(min(1 << 20, remaining))
        if not chunk:
            raise ValueError(
                _t("Truncated block at {position}: {missing} bytes missing.").format(
                    position=position, missing=remaining
                )
            )
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.hexdigest()


def _serialize_header(root) -> bytes:
    ET.register_namespace("", _XISF_NS)
    ET.register_namespace("xsi", _XSI_NS)
    return ET.tostring(root, encoding="utf8")


def add_checksums(path: str, algorithm: str = DEFAULT_CHECKSUM) -> int:
    """Add the ``checksum`` attribute to every attached block. Returns how many were set.

    A re-read pass after writing: the header grows by the added attributes, but the library
    aligns the blocks on 4 KiB, so the padding that follows the header nearly always suffices
    to absorb them without moving anything. Otherwise the blocks are shifted by a multiple of
    the alignment (file rewritten, atomic replacement).
    """
    if algorithm not in CHECKSUM_ALGORITHMS:
        raise ValueError(
            _t("Unknown checksum algorithm: {algorithm!r} (expected: {expected}).").format(
                algorithm=algorithm, expected=", ".join(sorted(CHECKSUM_ALGORITHMS))
            )
        )
    with open(path, "rb+") as f:
        _, header = _read_raw_header(f)
        root = ET.fromstring(header)
        blocks = _attached_blocks(root)
        if not blocks:
            return 0  # everything is inline/embedded: nothing to sign
        for elem, position, size in blocks:
            elem.set("checksum", f"{algorithm}:{_digest(f, position, size, algorithm)}")
        metadata = root.find(f"{{{_XISF_NS}}}Metadata")
        if metadata is not None:
            declared = ET.SubElement(
                metadata,
                f"{{{_XISF_NS}}}Property",
                {"id": "XISF:ChecksumAlgorithms", "type": "String"},
            )
            declared.text = algorithm

        new_header = _serialize_header(root)
        first_block = min(position for _, position, _ in blocks)
        if _HEADER_OFFSET + len(new_header) <= first_block:
            f.seek(len(_SIGNATURE))
            f.write(len(new_header).to_bytes(_HEADER_LEN_SIZE, "little"))
            f.seek(_HEADER_OFFSET)
            f.write(new_header)
            f.write(b"\0" * (first_block - f.tell()))
            return len(blocks)

    _rewrite_with_longer_header(path, root, blocks)
    return len(blocks)


def _rewrite_with_longer_header(path: str, root, blocks: list[tuple[ET.Element, int, int]]) -> None:
    """Rewrite the file, shifting the blocks — the signed header did not fit.

    The shift is a multiple of the alignment: the blocks stay aligned. The loop covers the
    case where the shift lengthens by one digit the positions written into the header.
    """
    shift = _ALIGN
    while True:
        for elem, position, size in blocks:
            elem.set("location", f"attachment:{position + shift}:{size}")
        header = _serialize_header(root)
        if _HEADER_OFFSET + len(header) <= min(p for _, p, _ in blocks) + shift:
            break
        shift += _ALIGN

    temporary = f"{path}.checksum-tmp"
    try:
        with open(path, "rb") as src, open(temporary, "wb") as dst:
            dst.write(_SIGNATURE)
            dst.write(len(header).to_bytes(_HEADER_LEN_SIZE, "little"))
            dst.write(b"\0" * _RESERVED_SIZE)
            dst.write(header)
            for _, position, size in sorted(blocks, key=lambda block: block[1]):
                dst.write(b"\0" * (position + shift - dst.tell()))
                src.seek(position)
                remaining = size
                while remaining > 0:
                    chunk = src.read(min(1 << 20, remaining))
                    dst.write(chunk)
                    remaining -= len(chunk)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def verify_checksums(path: str) -> int:
    """Verify the checksums present. Returns the number of blocks verified.

    Raises :class:`ValueError` on the first block whose digest does not match. A file with no
    checksum (the PixInsight case by default) returns 0 without saying anything: the absence
    of an annotation is not an integrity failure.
    """
    verified = 0
    with open(path, "rb") as f:
        _, header = _read_raw_header(f)
        for elem, position, size in _attached_blocks(ET.fromstring(header)):
            declared = elem.get("checksum", "")
            if not declared:
                continue
            algorithm, _, expected = declared.partition(":")
            if algorithm not in CHECKSUM_ALGORITHMS:
                raise ValueError(
                    _t("XISF checksum with unknown algorithm: {declared!r}.").format(
                        declared=declared
                    )
                )
            actual = _digest(f, position, size, algorithm)
            if actual != expected.strip().lower():
                raise ValueError(
                    _t(
                        "Invalid {algorithm} checksum for the block at {position} in {path}: "
                        "expected {expected}, computed {actual}. Corrupted file."
                    ).format(
                        algorithm=algorithm, position=position, path=path,
                        expected=expected, actual=actual,
                    )
                )
            verified += 1
    return verified


def load_xisf(path: str, *, verify: bool = True) -> tuple[Image, dict, object | None]:
    """Load a XISF. Returns ``(Image, keywords, STF | None)``.

    The keywords follow ``load_fits``'s contract: a flat dict, last occurrence per key
    (multiple ``HISTORY`` entries carry no machine meaning).

    ``verify`` checks the checksums present before decoding (raises ``ValueError`` on
    corruption); setting it to ``False`` saves a re-read of the blocks.
    """
    from ..model.stf import STF, ChannelSTF

    xisf = _require_xisf()
    if verify:
        verify_checksums(path)
    reader = xisf.XISF(path)
    data = np.asarray(reader.read_image(0), dtype=np.float32)
    if data.ndim == 2:
        data = data[:, :, np.newaxis]

    meta = reader.get_images_metadata()[0]
    keywords: dict = {}
    for name, values in meta.get("FITSKeywords", {}).items():
        if values:
            keywords[name] = _retype(str(values[-1].get("value", "")))

    stf = None
    prop = meta.get("XISFProperties", {}).get(STF_PROPERTY)
    if prop is not None and getattr(prop.get("value"), "ndim", 0) == 2:
        rows = np.asarray(prop["value"], dtype=np.float64)
        if rows.shape[1] >= 3:
            stf = STF(channels=[
                ChannelSTF(shadows=float(r[0]), midtones=float(r[1]), highlights=float(r[2]))
                for r in rows
            ])
    return Image(np.ascontiguousarray(data)), keywords, stf


def save_xisf(
    path: str,
    image: Image,
    keywords: dict | None = None,
    *,
    stf=None,
    codec: str | None = "lz4hc",
    shuffle: bool = True,
    level: int | None = None,
    checksum: str | None = DEFAULT_CHECKSUM,
) -> None:
    """Write a XISF: float32 pixels, FITS keywords, embedded STF, compressed, signed.

    ``codec=None`` disables compression; the library only keeps it anyway when it actually
    reduces the block's size. ``checksum=None`` writes no integrity digest at all (the
    PixInsight default).
    """
    from .. import __version__

    xisf = _require_xisf()
    # The xisf library expects a 3D (H, W, C) array, single-channel included.
    data = np.ascontiguousarray(image.data, dtype=np.float32)

    image_metadata: dict = {}
    if keywords:
        image_metadata["FITSKeywords"] = {
            str(name): [{"value": _keyword_text(value), "comment": ""}]
            for name, value in keywords.items()
        }
    if stf is not None and getattr(stf, "channels", None):
        matrix = np.array(
            [[c.shadows, c.midtones, c.highlights] for c in stf.channels],
            dtype=np.float32,
        )
        image_metadata["XISFProperties"] = {
            STF_PROPERTY: {"id": STF_PROPERTY, "type": "F32Matrix", "value": matrix},
        }

    xisf.XISF.write(
        path,
        data,
        creator_app=f"Retina {__version__}",
        image_metadata=image_metadata or None,
        codec=codec,
        shuffle=shuffle,
        level=level,
    )
    if checksum:
        add_checksums(path, checksum)


def _keyword_text(value) -> str:
    """Serialize a keyword value as FITS text (``T``/``F`` booleans)."""
    if value is True:
        return "T"
    if value is False:
        return "F"
    return str(value)
