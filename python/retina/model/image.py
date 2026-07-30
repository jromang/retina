"""Image — pixel container (numpy, HxWxC float32) and robust statistics.

The pixel buffer of the domain: pixel access, robust statistics (median/MAD…), and
``compute_auto_stretch``, which derives a display STF from linear data. No shell dependency —
the domain stays headless.
"""

from __future__ import annotations

import numpy as np

from ..i18n import translate as _t


class Image:
    """Floating-point image, stored as ``(H, W, C)`` float32.

    Data normally lies in ``[0, 1]`` (the linear astro convention), but nothing enforces
    that. Channel counts: 1 = grayscale, 3 = RGB.
    """

    __slots__ = ("_data",)

    def __init__(self, data: np.ndarray):
        arr = np.asarray(data)
        if arr.ndim == 2:
            arr = arr[:, :, np.newaxis]
        if arr.ndim != 3:
            raise ValueError(
                _t("Image expects a 2D or 3D array, got ndim={ndim}").format(ndim=arr.ndim)
            )
        self._data = np.ascontiguousarray(arr, dtype=np.float32)

    # --- construction ---------------------------------------------------------
    @classmethod
    def zeros(cls, height: int, width: int, channels: int = 1) -> Image:
        return cls(np.zeros((height, width, channels), dtype=np.float32))

    def with_data(self, data: np.ndarray) -> Image:
        """A new Image with the same semantics but different pixels."""
        return Image(data)

    def copy(self) -> Image:
        return Image(self._data.copy())

    # --- geometry / format ----------------------------------------------------
    @property
    def data(self) -> np.ndarray:
        return self._data

    @property
    def height(self) -> int:
        return self._data.shape[0]

    @property
    def width(self) -> int:
        return self._data.shape[1]

    @property
    def channels(self) -> int:
        return self._data.shape[2]

    @property
    def is_color(self) -> bool:
        return self.channels >= 3

    @property
    def is_grayscale(self) -> bool:
        return self.channels == 1

    # --- alpha channel ----------------------------------------------------------
    # Convention: channels beyond the nominal ones (1 for grayscale, 3 for color) are alpha
    # channels, the first of which is the display transparency.
    @property
    def nominal_channels(self) -> int:
        """1 for a grayscale image (with or without alpha), 3 beyond that."""
        return 1 if self.channels <= 2 else 3

    @property
    def has_alpha(self) -> bool:
        return self.channels > self.nominal_channels

    @property
    def alpha(self) -> np.ndarray | None:
        """(H, W) view on the first alpha channel, or ``None``."""
        if not self.has_alpha:
            return None
        return self._data[:, :, self.nominal_channels]

    @property
    def number_of_pixels(self) -> int:
        return self.height * self.width

    # --- pixel access ---------------------------------------------------------
    def sample(self, x: int, y: int, channel: int = 0) -> float:
        return float(self._data[y, x, channel])

    def set_sample(self, x: int, y: int, value: float, channel: int = 0) -> None:
        self._data[y, x, channel] = value

    def channel(self, c: int) -> np.ndarray:
        return self._data[:, :, c]

    # --- statistics (robust) --------------------------------------------------
    def mean(self, channel: int | None = None) -> float:
        return float(np.mean(self._select(channel)))

    def median(self, channel: int | None = None) -> float:
        return float(np.median(self._select(channel)))

    def std_dev(self, channel: int | None = None) -> float:
        return float(np.std(self._select(channel)))

    def mad(self, channel: int | None = None) -> float:
        """Median Absolute Deviation, unnormalized."""
        a = self._select(channel)
        return float(np.median(np.abs(a - np.median(a))))

    def madn(self, channel: int | None = None) -> float:
        """Normalized MAD (≈ standard deviation for a Gaussian): 1.4826 * MAD."""
        return 1.482602218505602 * self.mad(channel)

    def minimum(self, channel: int | None = None) -> float:
        return float(np.min(self._select(channel)))

    def maximum(self, channel: int | None = None) -> float:
        return float(np.max(self._select(channel)))

    def _select(self, channel: int | None) -> np.ndarray:
        return self._data if channel is None else self._data[:, :, channel]

    # --- display: auto-stretch (STF) ------------------------------------------
    def compute_auto_stretch(
        self, target_background: float = 0.25, shadows_clip: float = -2.8
    ):
        """Compute a per-channel auto-stretch :class:`~retina.model.stf.STF`.

        The standard auto-STF: derived from robust statistics (median + MADN).
        """
        from .stf import STF

        return STF.auto_from_image(
            self, target_background=target_background, shadows_clip=shadows_clip
        )

    def __repr__(self) -> str:
        return f"Image({self.width}x{self.height}, {self.channels}ch, float32)"
