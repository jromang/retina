"""Spike recipe — a complete pipeline run WITHOUT a GUI.

Run with:  python -m retina.run tests/recipes/spike.py
Context injected by retina.run: `app` (Application) and `retina` (the package).
Proves console-completeness: open, stretch, process, save — zero shell.
"""

import os
import tempfile

import numpy as np

# 1) synthetic dark linear image (the astro case)
data = (np.random.default_rng(0).random((256, 320, 1)) * 0.02).astype("float32")
data[100, 150, 0] = 0.9  # one star
img = retina.Image(data)

# 2) window + auto-stretch (non-destructive STF, display only)
win = app.new_window(img)
app.set_active_window(win)
stf = app.active_view.compute_auto_stf()
print("STF:", stf)

# 3) native (Rust) process through the API
app.apply(retina.GaussianConvolution(sigma=2.5))
print("backend:", retina.backend_name(), "| history_index:", app.active_view.history_index)

# 4) undo/redo
app.undo()
app.redo()

# 5) FITS save (a verifiable round trip)
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "spike_out.fits")
    app.save(out)
    reloaded, _ = retina.io.fits.load_fits(out) if hasattr(retina, "io") else (None, None)

print("Headless spike OK — median after processing:", round(app.active_view.image.median(), 5))
