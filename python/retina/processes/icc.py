"""ICC color management: AssignICCProfile, ICCProfileTransformation, ColorManagementSetup.

Our data is *scene-linear* float; ICC mostly concerns 8-16 bit **rendering/export**. We rely
on ``PIL.ImageCms`` (littlecms). ``AssignICCProfile`` attaches a profile to the window
(metadata, does not change the pixels); ``ICCProfileTransformation`` converts the pixels from
one space to another; ``ColorManagementSetup`` sets the global settings.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register

# global color management settings (ColorManagementSetup)
_CMS_SETTINGS = {"working_profile": "sRGB", "rendering_intent": "perceptual", "enabled": True}


def _load_profile(name_or_path: str):
    from PIL import ImageCms

    if not name_or_path or name_or_path.lower() == "srgb":
        return ImageCms.createProfile("sRGB")
    return ImageCms.getOpenProfile(name_or_path)  # path to an .icc/.icm file


@register
class ColorManagementSetup(Process):
    """Sets the global color management settings (global process)."""

    process_id = "ColorManagementSetup"
    category = "ColorManagement"
    is_global = True
    parameters = [
        Parameter("working_profile", "str", "sRGB", label=N_("Working profile")),
        Parameter("rendering_intent", "enum", "perceptual",
                  choices=("perceptual", "relative", "saturation", "absolute"),
                  label=N_("Rendering intent")),
        Parameter("enabled", "bool", True, label=N_("Color management enabled")),
    ]

    def execute_global(self, app) -> bool:
        _CMS_SETTINGS.update(
            working_profile=self.working_profile,
            rendering_intent=self.rendering_intent,
            enabled=bool(self.enabled),
        )
        return True


@register
class AssignICCProfile(Process):
    """Attaches an ICC profile to the window (metadata) without modifying the pixels."""

    process_id = "AssignICCProfile"
    category = "ColorManagement"
    is_maskable = False
    parameters = [Parameter("profile", "str", "sRGB", label=N_("Profile (name or .icc path)"))]

    def execute_on(self, view) -> bool:
        if view.window is not None:
            view.window.icc_profile = self.profile
        return True

    def execute_on_image(self, image):
        return image  # the profile lives on the window, not on the bare Image


@register
class ICCProfileTransformation(Process):
    """Converts the pixels from a source ICC profile to a target profile (PIL.ImageCms).

    Internal 16 bit encoding for the transformation, back to float ``[0,1]``. On a grayscale
    image, the conversion is applied after a pass through RGB. ``intent`` = rendering intent.
    """

    process_id = "ICCProfileTransformation"
    category = "ColorManagement"
    parameters = [
        Parameter("from_profile", "str", "sRGB", label=N_("Source profile")),
        Parameter("to_profile", "str", "sRGB", label=N_("Target profile")),
        Parameter("intent", "enum", "perceptual",
                  choices=("perceptual", "relative", "saturation", "absolute"),
                  label=N_("Rendering intent")),
    ]

    _INTENT = {"perceptual": 0, "relative": 1, "saturation": 2, "absolute": 3}

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from PIL import Image as PILImage
        from PIL import ImageCms

        rgb = data[:, :, :3] if data.shape[2] >= 3 else np.repeat(data[:, :, :1], 3, axis=2)
        u8 = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        pil = PILImage.fromarray(u8, mode="RGB")
        src = _load_profile(self.from_profile)
        dst = _load_profile(self.to_profile)
        converted = ImageCms.profileToProfile(
            pil, src, dst, renderingIntent=self._INTENT[self.intent], outputMode="RGB")
        out_rgb = np.asarray(converted, dtype=np.float32) / 255.0
        if data.shape[2] >= 3:
            out = data.copy()
            out[:, :, :3] = out_rgb
            return out
        return out_rgb.mean(axis=2, keepdims=True).astype(np.float32)
