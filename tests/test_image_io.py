"""Lossless I/O: FITS↔Image (and XISF when the package is present) + STF."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image
from retina.io.fits import load_fits, save_fits


def test_fits_roundtrip(fits_path):
    image, _keywords = load_fits(fits_path)
    assert image.channels == 1
    assert image.data.dtype == np.float32
    # write it back then re-read → identical
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "again.fits")
        save_fits(p, image)
        again, _ = load_fits(p)
    np.testing.assert_allclose(again.data, image.data, atol=1e-6)


def test_auto_stretch_brightens_dark_linear_image():
    """Real astro case: a dark linear image (low median) → the auto-stretch lifts the
    background towards ~0.25 (target background), making it visible without touching pixels."""
    rng = np.random.default_rng(3)
    # dark background ~0.01 + a few faint stars
    data = (rng.random((64, 96, 1)).astype(np.float32) * 0.02)
    data[20, 30, 0] = 0.6
    data[40, 70, 0] = 0.4
    image = Image(data)
    assert image.median() < 0.05  # good and dark

    stf = image.compute_auto_stretch()
    disp = stf.apply(image)
    assert disp.shape == image.data.shape
    # the median background must be lifted towards ~0.25 (the AutoSTF target background)
    assert 0.15 < float(np.median(disp)) < 0.35
    assert disp.mean() > image.mean() * 3  # markedly brighter
    assert disp.min() >= 0.0 and disp.max() <= 1.0


def test_xisf_roundtrip(tmp_path):
    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf

    src = Image((np.random.default_rng(0).random((32, 48, 1)) * 0.5).astype(np.float32))
    p = str(tmp_path / "roundtrip.xisf")
    save_xisf(p, src)
    back, keywords, stf = load_xisf(p)
    np.testing.assert_allclose(back.data, src.data, atol=1e-5)
    assert keywords == {}
    assert stf is None


def test_xisf_roundtrip_keywords(tmp_path):
    """Keywords travel, re-typed — the load_fits contract, applied to XISF.

    The pipeline compares GAIN/EXPTIME numerically: a '120.0' left as a string would
    break the grouping of frames re-read from an XISF library.
    """
    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf

    src = Image(np.zeros((8, 8, 1), dtype=np.float32))
    p = str(tmp_path / "kw.xisf")
    save_xisf(p, src, {"EXPTIME": 120.0, "GAIN": 100, "FILTER": "Ha", "SIMPLE": True})
    _, keywords, _ = load_xisf(p)
    assert keywords["EXPTIME"] == pytest.approx(120.0)
    assert keywords["GAIN"] == 100 and isinstance(keywords["GAIN"], int)
    assert keywords["FILTER"] == "Ha"
    assert keywords["SIMPLE"] is True


@pytest.mark.parametrize("codec", [None, "zlib", "lz4", "lz4hc", "zstd"])
def test_xisf_compression_yields_identical_pixels(tmp_path, codec):
    """Every codec (+ shuffle) gives back the same pixels — and compresses a smooth field."""
    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf

    y, x = np.mgrid[0:64, 0:64].astype(np.float32)
    src = Image(((x + y) / 256.0)[:, :, np.newaxis])
    p = str(tmp_path / f"c_{codec}.xisf")
    save_xisf(p, src, codec=codec, shuffle=codec is not None)
    back, _, _ = load_xisf(p)
    np.testing.assert_array_equal(back.data, src.data)
    if codec is not None:
        raw_path = str(tmp_path / "raw.xisf")
        save_xisf(raw_path, src, codec=None)
        import os

        assert os.path.getsize(p) < os.path.getsize(raw_path)


def test_xisf_checksums_are_written_and_verified(tmp_path):
    """Our XISF files carry an integrity fingerprint, and reading checks it."""
    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf, verify_checksums

    src = Image(np.random.default_rng(0).random((32, 24, 3)).astype(np.float32))
    p = str(tmp_path / "signed.xisf")
    save_xisf(p, src, {"EXPTIME": 120.0})

    assert verify_checksums(p) == 1
    back, keywords, _ = load_xisf(p)
    np.testing.assert_array_equal(back.data, src.data)
    assert keywords["EXPTIME"] == 120.0


def test_xisf_checksum_detects_corruption(tmp_path):
    """A single flipped byte in the block must be seen — that is the whole point of a checksum."""
    import os

    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf

    p = str(tmp_path / "corrupt.xisf")
    save_xisf(p, Image(np.random.default_rng(1).random((32, 32, 1)).astype(np.float32)))

    with open(p, "rb+") as f:
        f.seek(os.path.getsize(p) - 5)
        byte = f.read(1)[0]
        f.seek(os.path.getsize(p) - 5)
        f.write(bytes([byte ^ 0xFF]))

    with pytest.raises(ValueError, match="checksum"):
        load_xisf(p)
    load_xisf(p, verify=False)  # the escape hatch stays open


def test_xisf_without_checksum_reads_back_without_complaint(tmp_path):
    """Most writers emit none by default: their absence is not a defect."""
    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf, verify_checksums

    p = str(tmp_path / "bare.xisf")
    save_xisf(p, Image(np.zeros((8, 8, 1), dtype=np.float32)), checksum=None)
    assert verify_checksums(p) == 0
    load_xisf(p)


def test_xisf_checksum_when_the_header_overflows_the_alignment(tmp_path):
    """Edge case: the signed header no longer fits before the first block.

    The blocks are then shifted by a multiple of the alignment rather than corrupted.
    A ~4 KiB header is obtained through one bulky keyword; without this path, roughly one
    file in thirty would see its pixels overwritten by its own header.
    """
    import xml.etree.ElementTree as ET

    pytest.importorskip("xisf")
    from retina.io.xisf import _attached_blocks, _read_raw_header, load_xisf, save_xisf

    src = Image(np.random.default_rng(2).random((32, 32, 1)).astype(np.float32))

    def block_position(path):
        with open(path, "rb") as f:
            _, header = _read_raw_header(f)
        return _attached_blocks(ET.fromstring(header))[0][1]

    shifted = False
    for pad in range(2600, 2800):
        p = str(tmp_path / f"pad{pad}.xisf")
        save_xisf(p, src, {"COMMENT": "x" * pad}, checksum=None)
        before = block_position(p)
        save_xisf(p, src, {"COMMENT": "x" * pad}, checksum="sha512")
        if block_position(p) > before:
            shifted = True
            back, _, _ = load_xisf(p)  # checks the checksum along the way
            np.testing.assert_array_equal(back.data, src.data)
    assert shifted, "the tested range must cover at least one header overflow"


def test_xisf_roundtrip_stf(tmp_path):
    """The embedded STF comes back channel by channel (Retina:DisplayFunction property)."""
    pytest.importorskip("xisf")
    from retina.io.xisf import load_xisf, save_xisf
    from retina.model.stf import STF, ChannelSTF

    src = Image(np.zeros((4, 4, 3), dtype=np.float32))
    stf = STF(channels=[
        ChannelSTF(shadows=0.01, midtones=0.2, highlights=0.9),
        ChannelSTF(shadows=0.02, midtones=0.3, highlights=0.95),
        ChannelSTF(shadows=0.03, midtones=0.4, highlights=1.0),
    ])
    p = str(tmp_path / "stf.xisf")
    save_xisf(p, src, stf=stf)
    _, _, reread = load_xisf(p)
    assert reread is not None and len(reread.channels) == 3
    assert reread.channels[1].midtones == pytest.approx(0.3, abs=1e-6)
    assert reread.channels[2].shadows == pytest.approx(0.03, abs=1e-6)


def test_xisf_app_roundtrip(tmp_path):
    """Console parity: app.save then app.open recover keywords AND STF."""
    pytest.importorskip("xisf")
    from retina.app import Application
    from retina.model.stf import STF, ChannelSTF

    app = Application()
    win = app.new_window(Image(np.full((6, 6, 1), 0.25, dtype=np.float32)), window_id="X")
    win.keywords = {"OBJECT": "M31", "EXPTIME": 60.0}
    win.main_view.stf = STF(channels=[ChannelSTF(shadows=0.1, midtones=0.35, highlights=0.9)])
    path = str(tmp_path / "session.xisf")
    app.save(path)

    reread = app.open(path)
    assert reread.keywords["OBJECT"] == "M31"
    assert reread.keywords["EXPTIME"] == pytest.approx(60.0)
    assert reread.main_view.stf.channels[0].midtones == pytest.approx(0.35, abs=1e-6)


# --- FITS integer scaling (BZERO/BSCALE) ------------------------------------------------

def _write_unsigned_16bit(path, values):
    """Unsigned 16-bit FITS, camera style: signed integers + BZERO = 32768."""
    from astropy.io import fits

    hdu = fits.PrimaryHDU(np.asarray(values, dtype=np.uint16))
    hdu.writeto(path, overwrite=True)
    return str(path)


def test_an_unsigned_16_bit_fits_is_normalised(tmp_path):
    from retina.io import load_image_array

    path = _write_unsigned_16bit(tmp_path / "cam.fits",
                                 [[0, 32768], [65535, 1000]])
    data = load_image_array(path)

    assert data.min() == pytest.approx(0.0)
    assert data.max() == pytest.approx(1.0)


def test_banded_reading_gives_the_same_pixels(tmp_path):
    """This is the trap: astropy refuses memmap as soon as a BZERO is present."""
    from retina.io import load_image_array
    from retina.io.lazy import open_lazy

    rng = np.random.default_rng(0)
    path = _write_unsigned_16bit(
        tmp_path / "cam.fits", rng.integers(0, 65535, (24, 16), dtype=np.uint16))

    complete = load_image_array(path)
    with open_lazy(path) as image:
        chunks = [image.band(y, min(y + 7, 24)) for y in range(0, 24, 7)]

    assert np.allclose(np.concatenate(chunks, axis=0), complete, atol=1e-7)


def test_banded_reading_stays_memory_mapped(tmp_path):
    """Without this, tiling would fall back to a full load — on the most common format,
    which is precisely where it earns its keep."""
    from retina.io.lazy import _FitsImage

    path = _write_unsigned_16bit(tmp_path / "cam.fits", [[0, 65535], [1, 2]])
    with _FitsImage(path) as image:  # must not raise
        assert image._bzero == 32768.0
        assert image._scale == 65535.0


def test_bzero_is_never_copied_into_a_written_file(tmp_path):
    """Astropy would re-apply it on reading and add 32768 to every pixel."""
    from retina.io.fits import load_fits, save_fits

    source = _write_unsigned_16bit(tmp_path / "src.fits", [[1000, 2000], [3000, 4000]])
    image, keywords = load_fits(source)
    assert keywords["BZERO"] == 32768  # the source does carry it

    output = str(tmp_path / "out.fits")
    save_fits(output, image, keywords)
    reread, _ = load_fits(output)

    assert np.allclose(reread.data, image.data, atol=1e-6)
    assert reread.data.max() < 1.001


def test_useful_keywords_survive_filtering(tmp_path):
    from retina.io.fits import load_fits, save_fits
    from retina.model.image import Image

    output = str(tmp_path / "out.fits")
    save_fits(output, Image(np.zeros((4, 4, 1), dtype=np.float32)),
              {"FILTER": "Ha", "EXPTIME": 300.0, "BZERO": 32768})
    _, keywords = load_fits(output)

    assert keywords["FILTER"] == "Ha"
    assert keywords["EXPTIME"] == 300.0


# --- interop formats --------------------------------------------------------------------

def _checkerboard(h=16, w=24, channels=3) -> Image:
    rng = np.random.default_rng(11)
    return Image(rng.random((h, w, channels)).astype(np.float32))


@pytest.mark.parametrize("extension", [".webp", ".png", ".tif"])
def test_lossless_roundtrip(tmp_path, extension):
    """These three formats are written losslessly: what comes out must be what went in."""
    from retina.io import load_image_array, save_image

    image = _checkerboard()
    path = str(tmp_path / f"sample{extension}")
    save_image(path, image)
    reread = load_image_array(path)

    assert reread.shape == image.data.shape
    # 8 bits for WebP and PNG: the tolerance is half a quantisation step.
    tolerance = 1e-6 if extension == ".tif" else 1.0 / 255.0
    np.testing.assert_allclose(reread, image.data, atol=tolerance)


def test_webp_preserves_alpha(tmp_path):
    """This is what sets WebP apart from JPEG, and the natural outlet of a cut-out."""
    from retina.io import load_image_array, save_image

    rgba = np.zeros((8, 8, 4), np.float32)
    rgba[..., :3] = 0.6
    rgba[..., 3] = 0.25
    path = str(tmp_path / "with_alpha.webp")
    save_image(path, Image(rgba))

    reread = load_image_array(path)
    assert reread.shape[2] == 4
    np.testing.assert_allclose(reread[..., 3], 0.25, atol=1.0 / 255.0)


def test_jpeg_xl_roundtrip(tmp_path):
    # `pillow-jxl-plugin` is part of the `astro` extra, like tifffile and imageio; the skip
    # is only there for the minimal install, where nothing else would run either.
    pytest.importorskip("pillow_jxl")
    from retina.io import load_image_array, save_image

    image = _checkerboard()
    path = str(tmp_path / "sample.jxl")
    save_image(path, image)

    reread = load_image_array(path)
    assert reread.shape == image.data.shape
    np.testing.assert_allclose(reread, image.data, atol=1.0 / 255.0)


def test_an_unknown_extension_says_so(tmp_path):
    from retina.io import save_image

    with pytest.raises(ValueError, match="Unsupported extension"):
        save_image(str(tmp_path / "sample.xyz"), _checkerboard())
