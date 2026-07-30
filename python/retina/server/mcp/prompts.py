"""MCP prompts — two walkthroughs the agent does not have to reinvent.

A prompt is not a hidden instruction: it is a template *the user* explicitly picks in their
client. We limit ourselves to two, the ones that require domain knowledge an agent has no
reason to guess — in what order to preprocess a folder of raw frames, and how to judge a
linear image.

In English, like the tool descriptions.
"""

from __future__ import annotations

PROMPTS = {
    "preprocess_raw_folder": {
        "title": "Pre-process a folder of raw frames",
        "description": (
            "Calibrate, register and integrate a night of sub-exposures, then show the result."
        ),
        "arguments": [
            {"name": "path", "description": "Folder holding the raw frames.", "required": True},
        ],
    },
    "assess_image": {
        "title": "Assess an image",
        "description": "Look at a view, measure it, and report what is wrong with it.",
        "arguments": [
            {"name": "view", "description": "View id; defaults to the active view."},
        ],
    },
}


def list_prompts() -> list[dict]:
    return [{"name": name, **spec} for name, spec in PROMPTS.items()]


def get_prompt(name: str, arguments: dict) -> dict | None:
    spec = PROMPTS.get(name)
    if spec is None:
        return None
    text = _TEXT[name](arguments)
    return {
        "description": spec["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }


def _preprocess(arguments: dict) -> str:
    path = arguments.get("path") or "<folder>"
    return (
        f"Pre-process the raw astronomical frames in {path} using Retina's pipeline tool.\n\n"
        "Work in this order and report what you find at each step:\n"
        "1. pipeline(action='scan', path=…) — then tell me what the folder holds: how many "
        "lights, darks, flats and biases, which filters, and anything that looks wrong "
        "(missing calibration frames, mixed exposures, frames of a different target).\n"
        "2. pipeline(action='survey', …) — check that each light group has the masters it "
        "needs. Say so if one does not; do not silently proceed.\n"
        "3. pipeline(action='plan', …) — show me the outline and the disk usage before "
        "running anything.\n"
        "4. pipeline(action='run', …). This takes a long time; that is expected.\n"
        "5. Open the integrated result with open_images, apply set_stf(mode='auto') and "
        "render_view so we can both look at it, then give me your assessment.\n\n"
        "If measurements suggest some frames should be dropped, use "
        "pipeline(action='measures') to see them and set_rejects to exclude them from "
        "stacking — that keeps them calibrated and registered but gives them zero weight. "
        "Do not use 'exclude', which removes a file from the project entirely."
    )


def _assess(arguments: dict) -> str:
    view = arguments.get("view")
    target = f"view {view}" if view else "the active view"
    return (
        f"Assess {target} in Retina.\n\n"
        "Apply set_stf(mode='auto') if it is not already stretched, then render_view to look "
        "at it, and get_stats for the numbers. Comment on: background level and whether it "
        "is flat or gradient-affected, noise, star shape (apply DynamicPSF if you need FWHM "
        "and eccentricity), colour balance, and any clipping at either end of the histogram. "
        "Finish with the two or three processing steps you would actually recommend, and why "
        "— not a generic workflow."
    )


_TEXT = {"preprocess_raw_folder": _preprocess, "assess_image": _assess}
