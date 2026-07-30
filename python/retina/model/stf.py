"""STF — ScreenTransferFunction: a NON-destructive display transform.

The STF never modifies pixels: it maps linear data (often very dark) to a visible display,
through a per-channel Midtones Transfer Function (MTF) defined by
(shadows, midtones, highlights).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def mtf(m: float, x: np.ndarray | float) -> np.ndarray | float:
    """Midtones Transfer Function.

    ``m`` = the midtones balance, in ]0,1[. Edge cases handled.
    """
    x = np.asarray(x, dtype=np.float64)
    if m <= 0.0:
        return np.ones_like(x)
    if m >= 1.0:
        return np.zeros_like(x)
    if m == 0.5:
        return x  # identity
    num = (m - 1.0) * x
    den = (2.0 * m - 1.0) * x - m
    out = np.divide(num, den, out=np.zeros_like(x), where=den != 0.0)
    return out


@dataclass
class ChannelSTF:
    """STF parameters for one channel."""

    shadows: float = 0.0
    midtones: float = 0.5
    highlights: float = 1.0

    def apply(self, x: np.ndarray) -> np.ndarray:
        span = self.highlights - self.shadows
        if span <= 0.0:
            span = 1e-6
        xn = np.clip((x - self.shadows) / span, 0.0, 1.0)
        return np.asarray(mtf(self.midtones, xn), dtype=np.float32)

    def to_dict(self) -> dict:
        return {
            "shadows": float(self.shadows),
            "midtones": float(self.midtones),
            "highlights": float(self.highlights),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChannelSTF:
        base = cls()
        return cls(
            shadows=float(data.get("shadows", base.shadows)),
            midtones=float(data.get("midtones", base.midtones)),
            highlights=float(data.get("highlights", base.highlights)),
        )


@dataclass
class STF:
    """Multi-channel STF (one :class:`ChannelSTF` per image channel)."""

    channels: list[ChannelSTF] = field(default_factory=lambda: [ChannelSTF()])

    # --- application (display only) -------------------------------------------
    def apply(self, image) -> np.ndarray:
        """Return an ``(H, W, C)`` float32 array in [0,1], ready to display.

        Does not alter the source image. ``image`` may be an :class:`Image` or an ndarray.
        """
        # NB: an ndarray also has a ``.data`` attribute (a memoryview) → test the type
        data = image if isinstance(image, np.ndarray) else image.data
        data = np.asarray(data)
        if data.ndim == 2:
            data = data[:, :, np.newaxis]
        out = np.empty_like(data, dtype=np.float32)
        for c in range(data.shape[2]):
            ch = self.channels[c] if c < len(self.channels) else self.channels[-1]
            out[:, :, c] = ch.apply(data[:, :, c])
        return out

    # --- construction: AutoSTF ------------------------------------------------
    @classmethod
    def auto_from_image(
        cls, image, target_background: float = 0.25, shadows_clip: float = -2.8
    ) -> STF:
        chans: list[ChannelSTF] = []
        for c in range(image.channels):
            med = image.median(c)
            madn = image.madn(c)
            if madn == 0.0:
                madn = 1e-6
            if med < 0.5:
                # ordinary linear image (dark background)
                shadows = float(np.clip(med + shadows_clip * madn, 0.0, 1.0))
                highlights = 1.0
                x = med - shadows
                midtones = float(mtf(target_background, x))
            else:
                # inverted image (light background)
                shadows = 0.0
                highlights = float(np.clip(med - shadows_clip * madn, 0.0, 1.0))
                x = highlights - med
                midtones = float(1.0 - mtf(target_background, x))
            chans.append(ChannelSTF(shadows=shadows, midtones=midtones, highlights=highlights))
        return cls(channels=chans)

    # --- serialization ---------------------------------------------------------
    def to_dict(self) -> dict:
        """JSON form, identical to the one the snapshot already publishes to the frontend.

        One vocabulary for both uses (display and project): two forms would diverge, and the
        client already knows how to read this one.
        """
        return {"channels": [c.to_dict() for c in self.channels]}

    @classmethod
    def from_dict(cls, data: dict) -> STF:
        channels = [ChannelSTF.from_dict(c) for c in data.get("channels", ())]
        return cls(channels=channels or [ChannelSTF()])

    def __repr__(self) -> str:
        # Replayable in the console: `eval(repr(stf))` rebuilds the STF. The former form
        # (`STF([s=… m=… h=…])`) was readable but not executable, whereas `app.set_stf` echoes
        # it as is — the echo promised code that could not be pasted back.
        return "STF([" + ", ".join(
            f"ChannelSTF({c.shadows!r}, {c.midtones!r}, {c.highlights!r})" for c in self.channels
        ) + "])"
