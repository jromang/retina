"""Application — the root ``app`` object: the ONE source of truth.

Golden rule (see ARCHITECTURE.md § Console/GUI parity): all the application logic
(open, save, pick the active view, apply a process, undo/redo, batch) lives here.
The GUI calls ONLY these methods; the console reaches them too. ``app`` is
100% headless — no shell import.

The echo (``on_echo``) lets the GUI log the Python equivalent of every action
(Blender style), without the domain knowing anything about the GUI.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from .i18n import translate as _t
from .model.image import Image
from .model.view import View
from .model.window import ImageWindow
from .process.base import Process


class Application:
    def __init__(self) -> None:
        self.windows: list[ImageWindow] = []
        self._active: ImageWindow | None = None
        self.on_echo: Callable[[str], None] | None = None
        # GUI observer: the window list changed (open/new_window/close_window).
        # On the shell side, to be rebroadcast to clients from the loop (calls may come from
        # a worker thread — never a widget directly).
        self.on_windows_changed: Callable[[], None] | None = None
        # scriptable layout (docks/perspectives) — a no-op as long as the shell is absent
        from .layout import Layout

        self.layout = Layout(self._echo)
        # notification center — domain state, the GUI is only a view of it
        from .notifications import NotificationCenter

        self.notifications = NotificationCenter(self._echo)
        # Preferences — built right away, not lazily: the viewport defaults and the GPU flag
        # must be in place **before** the first window and the first computation, headless
        # included, where nobody will ever open a panel.
        from .preferences import Preferences, set_source

        self.preferences = Preferences(self._echo, lambda: self.session)
        set_source(lambda: self.preferences)
        self._wire_preferences()
        self._library = None  # library of recipes/instances (lazy)
        self._pipeline = None  # preprocessing facade (lazy)
        self._session = None  # recents + automatic reopening (lazy)
        #: Current project (path of the last `.retina` opened or saved), and the opaque
        #: document blob the shell deposited in it. The domain never interprets it: that is
        #: what lets an `open_project` followed by a `save_project` in **pure console** carry
        #: the user's tabs and buffers across without knowing anything about them.
        self._project_path: str | None = None
        self._project_documents: object | None = None
        #: ids of the windows whose cameras are synchronized (see `link_viewports`)
        self._linked: set[str] = set()
        self._blink = None  # the open Blink sequence, and its display window
        self._blink_window: ImageWindow | None = None
        # lets PixelMath (and friends) reference an open view by its id
        from .process import context

        context.set_image_provider(self._resolve_image)
        context.set_application(self)

    def _resolve_image(self, identifier: str):
        for win in self.windows:
            if identifier in (win.id, win.main_view.id):
                return win.main_view.image
            for pv in win.previews:
                if pv.id == identifier:
                    return pv.image
        return None

    # --- echo (console/GUI parity) -------------------------------------------
    def _echo(self, code: str) -> None:
        if self.on_echo is not None:
            self.on_echo(code)

    def notify(self, message: str, kind: str = "info", source: str = ""):
        """Post a durable notification — from a script as much as from the shell.

        ``app.notify("Masters ready")`` at the end of a recipe leaves a trace in the
        center (the GUI bell, ``app.notifications`` in the console) without depending
        on any interface.
        """
        return self.notifications.add(message, kind=kind, source=source)

    @property
    def pipeline(self):
        """Automated preprocessing (see :mod:`retina.pipeline`), with a Python echo.

        The domain stays callable directly from the console (``retina.pipeline.scan(...)``);
        this facade is what the GUI calls, so that every wizard gesture is written into
        the console as executable code.
        """
        if self._pipeline is None:
            from .pipeline.facade import PipelineFacade

            self._pipeline = PipelineFacade(echo=self._echo)
        return self._pipeline

    @property
    def library(self):
        """Library of named recipes/instances (see :mod:`retina.library`)."""
        if self._library is None:
            from .library import Library

            self._library = Library(echo=self._echo)
        return self._library

    def credits(self) -> str:
        """The bundled third-party components and their licenses, as readable text.

        `app.credits()` in the console returns the same thing as the "Licenses" panel — a
        free software package that does not say what it redistributes holds up its side of
        the bargain poorly. The structured detail is in :mod:`retina.credits`.
        """
        from .credits import to_text

        return to_text()

    def _wire_preferences(self) -> None:
        """Push down to the domain the settings it cannot come and fetch for itself.

        `model/` and `backend/` must know nothing of the application layer: it is therefore
        the application that sets their defaults, as it already does for the language source
        of `i18n`.
        """
        from .model import viewport_state

        def viewport(_value=None) -> None:
            viewport_state.configure_defaults(
                mask_display_mode=self.preferences.get("viewport.mask_display_mode"),
                transparency_mode=self.preferences.get("viewport.transparency_mode"),
                readout_probe_size=self.preferences.get("viewport.readout_probe_size"))

        for key in ("viewport.mask_display_mode", "viewport.transparency_mode",
                    "viewport.readout_probe_size"):
            self.preferences.add_applier(key, viewport)

    @property
    def session(self):
        """Recents, automatic reopening and language (see :mod:`retina.session`)."""
        if self._session is None:
            from . import i18n
            from .session import SessionStore

            self._session = SessionStore()
            # Language resolution must read the store the application writes, and not a
            # second instance: otherwise `set_language` would change a file that
            # `effective_language` does not look at.
            i18n.set_preference_source(self._session.language)
        return self._session

    # --- interface language ---------------------------------------------------
    @property
    def language(self) -> str:
        """The language actually served (``'en'``, ``'fr'``), after full resolution."""
        from . import i18n

        return i18n.effective_language()

    @property
    def language_override(self) -> str | None:
        """The user's explicit choice, or ``None`` if they follow the system."""
        return self.session.language()

    def set_language(self, language: str | None) -> None:
        """Choose the interface language. ``None`` hands control back to the system.

        The choice is persistent (``session.json``): it is a preference, not a session
        state. Clients already connected learn about the change through ``session.changed``
        and reload — labels are frozen when their modules are imported, as in any
        workbench.
        """
        self.session.set_language(language)
        self._echo(f"app.set_language({language!r})")

    # --- active view / window -------------------------------------------------
    @property
    def active_window(self) -> ImageWindow | None:
        return self._active

    @property
    def active_view(self) -> View | None:
        return self._active.current_view if self._active else None

    def set_active_window(self, window: ImageWindow) -> None:
        self._active = window
        self._echo(f"app.set_active_window(app.windows[{self.windows.index(window)}])")

    # --- view resolution / selection (main views AND previews) ----------------
    def view(self, identifier: str) -> View:
        """Resolve a view by identifier ("Image01", "Preview02"…). Pure read."""
        for win in self.windows:
            if identifier in (win.id, win.main_view.id):
                return win.main_view
            pv = win.preview_by_id(identifier)
            if pv is not None:
                return pv
        raise KeyError(_t("Unknown view: {id!r}").format(id=identifier))

    def select_view(self, view_or_id) -> View:
        """Make a view (main or preview) current — the target of processes/STF."""
        view = self.view(view_or_id) if isinstance(view_or_id, str) else view_or_id
        win = view.window
        if win is None:
            raise ValueError(_t("View without a window."))
        win.set_current_view(view)
        self._active = win
        self._echo(f"app.select_view({view.id!r})")
        return view

    def set_view_property(self, view_or_id, key: str, value) -> None:
        """Attach a piece of data to a view (measurements, notes) — the *view properties*.

        What makes them necessary: a measurement like ``DynamicPSF``'s costs a star
        detection and used to live only in the job-completion notification, hence lost on
        the slightest reconnection. Here it follows the view, and enters the ``.retina``
        project.

        ``value`` must be JSON-serializable; ``None`` removes the key.

        >>> app.set_view_property('Test01', 'psf', {'stars': [...]})
        """
        view = self.view(view_or_id) if isinstance(view_or_id, str) else view_or_id
        view.set_property(str(key), value)
        self._echo(f"app.set_view_property({view.id!r}, {key!r}, {value!r})")
        self._notify_windows()

    def view_property(self, view_or_id, key: str, default=None):
        """Read a view property. Read-only, hence no echo."""
        view = self.view(view_or_id) if isinstance(view_or_id, str) else view_or_id
        return view.get_property(str(key), default)

    def delete_preview(self, preview_id: str, window: ImageWindow | None = None) -> None:
        win = self._window_of_preview(preview_id, window)
        win.delete_preview(preview_id)
        self._echo(f"app.delete_preview({preview_id!r})")

    def rename_preview(self, old_id: str, new_id: str,
                       window: ImageWindow | None = None):
        win = self._window_of_preview(old_id, window)
        pv = win.rename_preview(old_id, new_id)
        self._echo(f"app.rename_preview({old_id!r}, {new_id!r})")
        return pv

    def modify_preview(self, preview_id: str, x0: int, y0: int, x1: int, y1: int,
                       window: ImageWindow | None = None):
        """Move/resize a preview (it resynchronizes its base)."""
        win = self._window_of_preview(preview_id, window)
        pv = win.preview_by_id(preview_id)
        pv.set_rect((x0, y0, x1, y1))
        if win.current_view is pv:
            win.set_current_view(pv)  # updates the viewport size
        self._echo(f"app.modify_preview({preview_id!r}, {x0}, {y0}, {x1}, {y1})")
        return pv

    def store_preview(self, preview_id: str, window: ImageWindow | None = None):
        """Freeze a volatile preview into a standalone object (cumulative history)."""
        win = self._window_of_preview(preview_id, window)
        pv = win.preview_by_id(preview_id)
        pv.store()
        self._echo(f"app.store_preview({preview_id!r})")
        return pv

    def _window_of_preview(self, preview_id: str,
                           window: ImageWindow | None) -> ImageWindow:
        if window is not None:
            if window.preview_by_id(preview_id) is None:
                raise KeyError(_t("Unknown preview: {id!r}").format(id=preview_id))
            return window
        for win in self.windows:
            if win.preview_by_id(preview_id) is not None:
                return win
        raise KeyError(_t("Unknown preview: {id!r}").format(id=preview_id))

    # --- opening / creation ---------------------------------------------------
    def _notify_windows(self) -> None:
        if self.on_windows_changed is not None:
            self.on_windows_changed()

    def new_window(
        self, image: Image, window_id: str = "", file_path: str | None = None
    ) -> ImageWindow:
        win = ImageWindow(image, window_id=window_id, file_path=file_path)
        self.windows.append(win)
        self._active = win
        self._notify_windows()
        return win

    def close_window(self, window: ImageWindow | None = None) -> None:
        """Close an image window (default: the active one). The image is dropped —
        the view's history is not recoverable after closing."""
        win = window or self._active
        if win is None or win not in self.windows:
            return
        self.windows.remove(win)
        # A closed window can no longer be linked: without this removal,
        # `linked_viewports()` would keep announcing an id that designates nothing, and
        # reopening an image bearing the same id would find it linked without anyone asking.
        self._linked.discard(win.id)
        if self._active is win:
            self._active = self.windows[-1] if self.windows else None
        self._echo("app.close_window()")
        self._notify_windows()

    def open(self, path: str) -> ImageWindow:
        """Open an image file (FITS/XISF depending on the extension)."""
        ext = os.path.splitext(path)[1].lower()
        if ext in (".fits", ".fit", ".fts"):
            from .io.fits import load_fits

            image, keywords = load_fits(path)
        elif ext == ".xisf":
            from .io.xisf import load_xisf

            image, keywords, stf = load_xisf(path)
            win = self.new_window(image, file_path=path)
            win.keywords = keywords
            from .io.fits import celestial_wcs

            win.wcs = celestial_wcs(keywords)  # XISF carries the FITS keywords, WCS included
            if stf is not None:  # embedded STF: the screen recovers the recorded stretch
                win.main_view.stf = stf
            self.session.add_recent_file(path)
            self._echo(f"app.open({path!r})")
            return win
        else:
            raise ValueError(_t("Unsupported extension: {ext}").format(ext=ext))
        win = self.new_window(image, file_path=path)
        win.keywords = keywords
        # An already-solved file carries its solution in its header: reading it back here
        # avoids asking for another plate-solve on a field whose astrometry is known.
        from .io.fits import celestial_wcs

        win.wcs = celestial_wcs(keywords)
        self.session.add_recent_file(path)
        self._echo(f"app.open({path!r})")
        return win

    def reload(self, window: ImageWindow | None = None) -> ImageWindow:
        """Re-read a window's source file — close and reopen, but **in place**.

        The missing gesture when the file has been modified from the outside (another
        program, a script, a synchronized folder): without it, one had to close the window
        and reopen it, which loses its place in the layout, its viewport link and its id.

        The window itself survives intact: same id, same zoom, same mask. What starts over
        from scratch (history, astrometry, previews) is detailed in
        :meth:`ImageWindow.replace_image`.
        """
        win = window or self._active
        if win is None:
            raise RuntimeError(_t("No active window to reload."))
        path = win.file_path
        if not path:
            raise RuntimeError(
                _t("This window has no source file on disk — nothing to reload.")
            )
        # Twin of `open`'s dispatch above. At the third format, extract a common loader
        # returning (image, keywords, STF) rather than lining up three extension
        # cascades.
        ext = os.path.splitext(path)[1].lower()
        stf = None
        if ext in (".fits", ".fit", ".fts"):
            from .io.fits import load_fits

            image, keywords = load_fits(path)
        elif ext == ".xisf":
            from .io.xisf import load_xisf

            image, keywords, stf = load_xisf(path)
        else:
            raise ValueError(_t("Unsupported extension: {ext}").format(ext=ext))
        win.replace_image(image, keywords=keywords, stf=stf)
        # `replace_image` drops the solution, which described the old content; the new
        # file's own solution does describe what we have just read.
        from .io.fits import celestial_wcs

        win.wcs = celestial_wcs(keywords)
        # Explicit echo when the target is not the active window: replaying `app.reload()`
        # in another activation order would not reload the same image.
        self._echo(
            "app.reload()" if win is self._active
            else f"app.reload(app.windows[{self.windows.index(win)}])"
        )
        self._notify_windows()
        return win

    def save(self, path: str, window: ImageWindow | None = None,
             stretch: bool = False) -> None:
        """Write the window's main view to ``path``, the format following the extension.

        FITS and XISF carry the linear data as it is; TIFF keeps 32-bit float; PNG, JPEG,
        WebP, JPEG 2000 and JPEG XL quantize (see :mod:`retina.io.raster`).

        ``stretch=True`` bakes the view's screen transfer function into **the exported copy
        only** — the pixels in the session do not move. Without it, an 8-bit export of a
        linear image is black, since a linear sky background sits around 1e-3: this is the
        difference between what the screen shows and what the file holds.
        """
        win = window or self._active
        if win is None:
            raise RuntimeError(_t("No active window to save."))
        # The live solution takes precedence over the keywords inherited from the source
        # file: a PlateSolve done inside Retina must end up in what we write, otherwise it
        # would have to be redone on every reopening.
        from .io import save_image
        from .io.fits import wcs_keywords

        keywords = {**win.keywords, **wcs_keywords(win.wcs)}
        view = win.main_view
        image = view.image
        stf = view.stf
        if stretch:
            from .model.image import Image

            image = Image(stf.apply(image))
            # The stretch is now IN the pixels: also recording it would make a reader apply
            # it a second time.
            stf = None
        save_image(path, image, keywords, stf=stf)
        self._echo(f"app.save({path!r}{', stretch=True' if stretch else ''})")

    # --- projects (.retina) ---------------------------------------------------
    @property
    def project_path(self) -> str | None:
        """Path of the current project, or ``None`` if the session was never saved."""
        return self._project_path

    def save_project(self, path: str | None = None, documents: object | None = None) -> dict:
        """Save the whole session — windows, previews, masks, **all** history states — into
        a ``.retina`` file.

        ``documents`` is the shell's opaque blob (script tabs and their unsaved buffers,
        recipes in progress, transcript). When omitted, we rewrite the one the session
        already carries: that is what makes an ``open_project`` then ``save_project`` in
        pure console harmless to the user's work.

        >>> app.save_project('/data/m31.retina')
        """
        from .io.project import save_project as _save

        target = path or self._project_path
        if not target:
            raise ValueError(
                _t("No current project: give a path "
                   "(app.save_project('/.../x.retina')).")
            )
        if documents is None:
            documents = self._project_documents
        resume = _save(self, target, documents=documents)
        self._project_path = resume["path"]
        self.session.add_recent_project(resume["path"])
        self._echo(f"app.save_project({resume['path']!r})")
        return resume

    def open_project(self, path: str):
        """Replace the current session with the one from the project at ``path``.

        Returns a :class:`~retina.io.project.ProjectReport`: the restored windows, and what
        went wrong — unavailable processes, scripts moved or modified. Those three lists are
        returned **at opening time** and not on the first replay, because that is when the
        user can still act.

        >>> app.open_project('/data/m31.retina')
        """
        from .io.project import load_project as _load

        report = _load(self, path)
        self._project_path = report.path
        self._project_documents = report.documents
        self.session.add_recent_project(report.path)
        self._echo(f"app.open_project({path!r})")
        return report

    def close_project(self) -> None:
        """Close every window and forget the current project."""
        self.windows.clear()
        self._active = None
        self._linked = set()
        self._project_path = None
        self._project_documents = None
        self._echo("app.close_project()")
        self._notify_windows()

    def set_project_documents(self, documents: object | None) -> None:
        """Deposit the shell's blob, without an echo.

        This is a **report** from the client to the domain, not a user action — the same
        category as ``layout.report`` or ``layout.store_perspective``. Echoing it would fill
        the console with a line on every keystroke in a script editor.
        """
        self._project_documents = documents

    def project_documents(self) -> object | None:
        """The shell's blob exactly as it was deposited. Pure read."""
        return self._project_documents

    def recent_files(self) -> list[str]:
        """Recently opened image files, most recent first. Pure read."""
        return self.session.recent_files()

    def recent_projects(self) -> list[str]:
        """Recently opened or saved projects. Pure read."""
        return self.session.recent_projects()

    def download_sample(self, sample_id: str = "") -> str:
        """Download a sample set of raw frames and return the folder, ready to preprocess.

        An empty identifier takes the one the manifest designates as the default — the
        smallest, the one to put in front of a newcomer. The full catalogue is read with
        ``retina.samples.catalogue()``.

        The echo is posted **afterwards**, not before: a download that fails (network down,
        wrong digest) produced nothing, and writing into the console a line that did not
        succeed would teach something false.

        >>> app.download_sample("example-cryo-lfc")
        '/home/…/.cache/retina/samples/example-cryo-lfc/example-cryo-LFC'
        """
        from .samples import ensure, resolve_id

        identifier = resolve_id(sample_id)
        folder = str(ensure(identifier))
        self._echo(f"app.download_sample({identifier!r})")
        return folder

    def keywords(self, window: ImageWindow | None = None) -> dict:
        """FITS keywords of the window (default: the active one), exactly as they were read.

        Pure read — nothing to echo. Purely structural keys (``NAXIS``, ``BITPIX``…) are
        set aside: they describe the file on disk, not the observation, and would drown the
        few lines one opens a header to read.

        >>> app.keywords()["EXPTIME"]
        300.0
        """
        win = window or self._active
        if win is None:
            raise RuntimeError(_t("No active window."))
        from .io.fits import STRUCTURAL_KEYWORDS

        return {k: v for k, v in win.keywords.items() if k not in STRUCTURAL_KEYWORDS}

    # --- sequence inspection (Blink) ------------------------------------------
    def blink(self, frames) -> object:
        """Open a sequence of raw frames and display the first — see :class:`Blink`.

        The sequence stays **lazy**: only the headers are read on opening, the pixels come
        when visited. Five hundred exposures therefore open as fast as three.

        >>> session = app.blink(sorted(glob.glob('/data/M31/*.fits')))
        >>> app.blink_step(1)
        1
        """
        from .processes.inspection import Blink

        self._blink = Blink(frames=[str(f) for f in frames])
        self._blink.load()
        self._blink_window = self._blink.show(self)
        self._echo(f"app.blink({[str(f) for f in frames]!r})")
        self._notify_windows()
        return self._blink

    def blink_step(self, delta: int = 1) -> int:
        """Step forward (or back) by one frame and update the window."""
        return self._blink_go(lambda b: b.step(delta), f"app.blink_step({delta})")

    def blink_go_to(self, index: int) -> int:
        """Jump to a given rank in the sequence."""
        return self._blink_go(lambda b: b.go_to(index), f"app.blink_go_to({index})")

    def _blink_go(self, move, code: str) -> int:
        blink = getattr(self, "_blink", None)
        if blink is None:
            raise RuntimeError(_t("No open sequence - call app.blink(frames) first."))
        index = move(blink)
        # The window may have been closed in the meantime: we reopen one rather than raise,
        # otherwise a click on "next" would become an error for a harmless gesture.
        window = getattr(self, "_blink_window", None)
        if window not in self.windows:
            window = None
        self._blink_window = blink.show(self, window)
        if window is None:
            self._notify_windows()
        self._echo(code)
        return index

    def blink_state(self) -> dict | None:
        """State of the open sequence: current rank, window, stats of the visited frame.

        Pure read. The statistics are those of the **current** frame only: computing them
        for the whole sequence would make lazy loading pointless.
        """
        blink = getattr(self, "_blink", None)
        if blink is None:
            return None
        window = getattr(self, "_blink_window", None)
        return {
            "index": blink.index,
            "count": len(blink),
            "frames": list(blink.frames),
            "window": window.id if window in self.windows else None,
            "stats": blink.current_stats(),
        }

    # --- processing -----------------------------------------------------------
    def apply(self, process, view: View | None = None) -> bool:
        """Apply a configured process — or a whole :class:`ProcessContainer` — to a View
        (default: the active view).

        If the process asks for a new image (``create_new_image``), the result is placed in
        a new window instead of modifying the target view. The echo targets the real view
        (``app.view('Preview01')`` when it is not the active view).
        """
        target = view or self.active_view
        if target is None:
            raise RuntimeError(_t("No target view."))
        target_expr = ("app.active_view" if target is self.active_view
                       else f"app.view({target.id!r})")
        from .process.container import ProcessContainer

        if isinstance(process, ProcessContainer):
            # Explicit resolver: the container designates its masks by view identifier, and
            # it is the application that knows how to translate them. Passing it in rather
            # than letting it reach for the singleton keeps the domain testable on a fresh
            # instance.
            ok = process.execute_on(target, resolve_mask=lambda vid: self.view(vid).image)
            self._echo(process.to_python_source(target_expr))
            return ok
        if getattr(process, "create_new_image", False) or getattr(process, "creates_window", False):
            result = process.execute_on_image(target.image)
            src_id = target.window.id if target.window is not None else "Image"
            new_id = getattr(process, "new_image_id", "") or f"{src_id}_{process.process_id}"
            self.new_window(result, window_id=new_id)
            self._echo(process.to_python_source(target_expr))
            return True
        ok = process.execute_on(target)
        self._echo(process.to_python_source(target_expr))
        return ok

    def run(self, process: Process) -> bool:
        """Unified entry point: global process → ``execute_global``; otherwise → active view."""
        if getattr(process, "is_global", False):
            ok = process.execute_global(self)
            self._echo(process.to_python_source("app"))
            return ok
        return self.apply(process)

    # --- mask -----------------------------------------------------------------
    def set_mask(self, mask_source, window: ImageWindow | None = None) -> None:
        """Set the window's mask. ``mask_source`` = a view/window id or an Image."""
        win = window or self._active
        if win is None:
            raise RuntimeError(_t("No active window."))
        source_id = mask_source if isinstance(mask_source, str) else None
        if source_id is not None:
            img = self._resolve_image(source_id)
            if img is None:
                raise ValueError(_t("Mask not found: {source!r}").format(source=mask_source))
        else:
            img = mask_source
        # The id is kept: it is what the history records so a step can be replayed with the
        # mask that was used, and not the window's mask at replay time.
        win.set_mask(img, source_id=source_id)
        self._echo(f"app.set_mask({mask_source!r})")

    def remove_mask(self, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.remove_mask()
            self._echo("app.remove_mask()")

    def set_mask_inverted(self, inverted: bool, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.mask_inverted = bool(inverted)
            self._echo(f"app.set_mask_inverted({bool(inverted)})")

    def set_mask_enabled(self, enabled: bool, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.mask_enabled = bool(enabled)
            self._echo(f"app.set_mask_enabled({bool(enabled)})")

    # --- display / viewport (parity: everything scriptable + echoed) ----------
    def _camera(self, window: ImageWindow | None, move, code: str) -> None:
        """Apply a camera gesture, echo it, and propagate it to the linked views.

        The six viewport gestures all pass through here: it is the only place propagation
        has to be wired, and the only way to guarantee a future gesture will not forget it.
        """
        win = window or self._active
        if win is None:
            return
        move(win.viewport)
        self._echo(code)
        self._sync_linked(win)

    def set_zoom(self, zoom: float, window: ImageWindow | None = None) -> None:
        self._camera(window, lambda v: v.set_zoom(float(zoom)),
                     f"app.set_zoom({float(zoom)!r})")

    def zoom_in(self, pivot=None, window: ImageWindow | None = None) -> None:
        self._camera(window, lambda v: v.zoom_in(pivot),
                     f"app.zoom_in(pivot={tuple(pivot)!r})" if pivot else "app.zoom_in()")

    def zoom_out(self, pivot=None, window: ImageWindow | None = None) -> None:
        self._camera(window, lambda v: v.zoom_out(pivot),
                     f"app.zoom_out(pivot={tuple(pivot)!r})" if pivot else "app.zoom_out()")

    def zoom_1_1(self, window: ImageWindow | None = None) -> None:
        self._camera(window, lambda v: v.zoom_1_1(), "app.zoom_1_1()")

    def zoom_to_fit(
        self, allow_magnification: bool = False, window: ImageWindow | None = None
    ) -> None:
        self._camera(
            window, lambda v: v.zoom_to_fit(allow_magnification=allow_magnification),
            f"app.zoom_to_fit(allow_magnification={bool(allow_magnification)})")

    def set_viewport(self, center, zoom=None, window: ImageWindow | None = None) -> None:
        self._camera(window, lambda v: v.set_viewport(center, zoom),
                     f"app.set_viewport({tuple(center)!r}, zoom={zoom!r})")

    # --- linked views ---------------------------------------------------------
    def _resolve_window(self, window) -> ImageWindow:
        if not isinstance(window, str):
            return window
        for win in self.windows:
            if win.id == window:
                return win
        raise KeyError(_t("Unknown window: {window!r}").format(window=window))

    def link_viewports(self, windows=None) -> list[str]:
        """Link viewports: panning or zooming one moves the others.

        With no argument, links **all** open windows — the common case, comparing the
        channels of one target. Linked windows immediately adopt the active window's camera,
        failing which the first gesture would make the others jump without one knowing where
        they came from.

        The camera propagates in **image** coordinates: linked windows show the *same
        pixel*, not the same fraction of the frame. That is the intended behavior for what
        linking is for — comparing exposures of one target, which share their grid. Between
        two images of different sizes, the smaller one can therefore end up centered out of
        frame; the domain allows that center, just as it allows panning past the edge.

        >>> app.link_viewports()
        ['Image01', 'Image02']
        """
        targets = (list(self.windows) if windows is None
                  else [self._resolve_window(w) for w in windows])
        self._linked = {win.id for win in targets}
        self._echo("app.link_viewports()" if windows is None
                   else f"app.link_viewports({[w.id for w in targets]!r})")
        source = self._active if self._active in targets else (targets[0] if targets else None)
        self._sync_linked(source)
        return sorted(self._linked)

    def unlink_viewports(self) -> None:
        """Unlink every viewport."""
        self._linked = set()
        self._echo("app.unlink_viewports()")

    def linked_viewports(self) -> list[str]:
        """Ids of the currently linked windows. Pure read."""
        return sorted(getattr(self, "_linked", set()))

    def _sync_linked(self, source: ImageWindow | None) -> None:
        """Copy ``source``'s camera onto the other linked windows.

        No reentrancy guard: ``ViewportState.set_viewport`` notifies its display observer,
        it never comes back through ``app``. Adding a lock here would suggest a cycle that
        does not exist.
        """
        linked = getattr(self, "_linked", set())
        if source is None or source.id not in linked:
            return
        camera = source.viewport
        for win in self.windows:
            if win.id != source.id and win.id in linked:
                win.viewport.set_viewport(camera.center, camera.zoom)

    def set_display_channel(self, channel: str, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.viewport.set_display_channel(channel)
            self._echo(f"app.set_display_channel({channel!r})")

    def set_stf_enabled(self, enabled: bool, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.viewport.set_stf_enabled(bool(enabled))
            if win.current_view is not None:
                win.current_view.stf_enabled = bool(enabled)
            self._echo(f"app.set_stf_enabled({bool(enabled)})")

    def compute_auto_stf(self, window: ImageWindow | None = None):
        """Compute and install an auto-stretch STF on the active view."""
        win = window or self._active
        if win is None or win.current_view is None:
            return None
        stf = win.current_view.compute_auto_stf()
        self._echo("app.compute_auto_stf()")
        return stf

    def set_stf(self, stf, window: ImageWindow | None = None) -> None:
        """Install an explicit STF on the active view (interactive editing)."""
        win = window or self._active
        if win is not None and win.current_view is not None:
            win.current_view.stf = stf
            self._echo(f"app.set_stf({stf!r})")

    def apply_stf(self, window: ImageWindow | None = None):
        """Write the screen stretch into the pixels, and reset the STF to the identity.

        The step from "I have found the right display" to "this is now the image": until it
        existed, the values had to be read off the histogram panel and typed back into a
        HistogramTransformation form by hand. It goes through that very process, so the
        result is an ordinary history entry, undoable, and the echo is the process itself
        rather than a gesture of its own.

        Returns the process applied, or ``None`` when the STF is the identity — there is
        nothing to bake then, and pushing a history entry that changes no pixel would only
        make the undo stack lie about what happened.
        """
        win = window or self._active
        if win is None or win.current_view is None:
            raise RuntimeError(_t("No target view."))
        view = win.current_view
        from .model.stf import STF, ChannelSTF
        from .processes.histogram import HistogramTransformation

        process = HistogramTransformation.from_stf(view.stf)
        if not process.channels and (process.shadows, process.midtones, process.highlights) == (
            0.0, 0.5, 1.0
        ):
            return None
        # Through `apply`, not `execute_on`: that is what pushes the history entry and echoes
        # the process itself. The console then reads the line one would have written by hand,
        # not a gesture of the interface.
        self.apply(process, view)
        # The stretch now lives in the pixels: leaving the STF in place would display it a
        # second time, and the image would look stretched twice — because it would be.
        view.stf = STF(channels=[ChannelSTF() for _ in view.stf.channels])
        return process

    def set_interaction_mode(self, mode, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.viewport.set_interaction_mode(mode)
            self._echo(f"app.set_interaction_mode(retina.InteractionMode.{mode.name})")

    def set_mask_display_mode(self, mode, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.viewport.set_mask_display_mode(mode)
            self._echo(f"app.set_mask_display_mode(retina.MaskDisplayMode.{mode.name})")

    def set_mask_visible(self, visible: bool, window: ImageWindow | None = None) -> None:
        """Show or hide the mask on screen — without changing its effect on processes."""
        win = window or self._active
        if win is not None:
            win.viewport.set_mask_visible(visible)
            self._echo(f"app.set_mask_visible({bool(visible)})")

    def set_transparency_mode(self, mode, window: ImageWindow | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.viewport.set_transparency_mode(mode)
            self._echo(f"app.set_transparency_mode(retina.TransparencyMode.{mode.name})")

    def add_overlay(self, kind: str, window: ImageWindow | None = None, tag: str = "", **data):
        """Paint a vector overlay on the viewport. See :meth:`ViewportState.add_overlay`."""
        win = window or self._active
        if win is None:
            return None
        overlay = win.viewport.add_overlay(kind, tag=tag, **data)
        args = [repr(kind)]
        if tag:
            args.append(f"tag={tag!r}")
        args += [f"{k}={v!r}" for k, v in data.items()]
        self._echo(f"app.add_overlay({', '.join(args)})")
        return overlay

    def set_overlays(self, tag: str, overlays: list[dict], window: ImageWindow | None = None):
        """Replace all overlays carrying one tag, in a single gesture.

        See :meth:`~retina.model.viewport_state.ViewportState.set_overlays`.
        """
        win = window or self._active
        if win is None:
            return None
        posés = win.viewport.set_overlays(tag, overlays)
        self._echo(f"app.set_overlays({tag!r}, {overlays!r})")
        return posés

    def clear_overlays(self, window: ImageWindow | None = None, tag: str | None = None) -> None:
        win = window or self._active
        if win is not None:
            win.viewport.clear_overlays(tag)
            self._echo(f"app.clear_overlays({f'tag={tag!r}' if tag else ''})")

    def set_readout_options(self, window: ImageWindow | None = None, **kw) -> None:
        win = window or self._active
        if win is None:
            return
        opts = win.viewport.readout
        for key, value in kw.items():
            if not hasattr(opts, key):
                raise ValueError(_t("Unknown readout option: {key!r}").format(key=key))
            setattr(opts, key, value)
        self._echo(f"app.set_readout_options({', '.join(f'{k}={v!r}' for k, v in kw.items())})")

    def readout(self, x: float, y: float, n: int | None = None, window: ImageWindow | None = None):
        """Probe statistics at image point (x, y). See :meth:`ImageWindow.readout`."""
        win = window or self._active
        return None if win is None else win.readout(x, y, n)

    def new_preview(self, x0: int, y0: int, x1: int, y1: int, preview_id: str = "",
                    window: ImageWindow | None = None):
        win = window or self._active
        if win is None:
            raise RuntimeError(_t("No active window."))
        pv = win.create_preview(x0, y0, x1, y1, preview_id)
        self._echo(f"app.new_preview({x0}, {y0}, {x1}, {y1}, {pv.id!r})")
        return pv

    def undo(self) -> bool:
        if self._active is None:
            return False
        ok = self._active.undo()
        self._echo("app.undo()")
        return ok

    def redo(self) -> bool:
        if self._active is None:
            return False
        ok = self._active.redo()
        self._echo("app.redo()")
        return ok

    def go_to_history(self, index: int, window: ImageWindow | None = None) -> bool:
        """Jump to a state in the current view's history (History panel)."""
        win = window or self._active
        if win is None:
            return False
        ok = win.current_view.go_to(int(index))
        self._echo(f"app.go_to_history({int(index)})")
        return ok

    def replay_history(self, index: int, values: dict | None = None,
                       window: ImageWindow | None = None) -> bool:
        """Replay a past step with different parameters, and recompute everything downstream.

        Revisiting a setting made three steps earlier without redoing it all by hand. See
        :meth:`retina.model.view.View.replay` for what is guaranteed — bit-for-bit fidelity
        at unchanged values, the mask of the time replayed, and an atomic refusal if a step
        is not replayable.

        >>> app.replay_history(1, {"sigma": 3.5})
        """
        win = window or self._active
        if win is None:
            raise RuntimeError(_t("No active window."))
        ok = win.current_view.replay(int(index), values)
        self._echo(f"app.replay_history({int(index)}, {dict(values or {})!r})")
        return ok

    # --- recipes / scripts ----------------------------------------------------
    def run_recipe(self, path: str) -> None:
        """Execute a Python recipe file with ``app`` and ``retina`` in context.

        A **fresh** namespace on every call, and ``__file__`` filled in: a recipe can
        therefore resolve its resources relative to itself, like any Python script. That is
        what distinguishes this gesture from "run the buffer in the console", where one
        wants on the contrary to keep the state shared with the prompt.

        If the script **exports parameters** (``retina.parameters.set(...)``), running it
        leaves a :class:`~retina.processes.script.Script` instance in the active view's
        history: it undoes, files into the library and replays, like any other process. That
        is the rule, and it is what avoids the duplicate — a script that merely calls
        ``app.apply(...)`` already leaves its history step by step, and has no business
        adding an entry that would describe it a second time.
        """
        import retina

        from .process.parameters import ParameterContext, current, set_context

        resolved = str(Path(path).expanduser().resolve())
        namespace = {"app": self, "retina": retina, "__file__": resolved, "__name__": "__main__"}
        with open(resolved, encoding="utf-8") as fh:
            code = fh.read()
        # Echo before execution: if the recipe fails, the console still shows what was
        # attempted — that is the line one wants to be able to copy back to replay.
        self._echo(f"app.run_recipe({resolved!r})")

        # A context already installed means we are **replaying** a `Script` instance: it is
        # the one holding the parameters, and it must not register itself again.
        replaying = current() is not None
        if not replaying:
            set_context(ParameterContext(target_view=self.active_view))
        try:
            exec(compile(code, resolved, "exec"), namespace)
            if not replaying:
                self._record_script(resolved)
        finally:
            if not replaying:
                set_context(None)

    def _record_script(self, path: str) -> None:
        """Push a ``Script`` instance into the history, if the script declared itself."""
        from .process.parameters import current
        from .processes.script import Script, file_digest

        context = current()
        if context is None or not context.values:
            return
        target = context.target_view or self.active_view
        if target is None:
            return
        instance = Script(
            path=path,
            exported_values=json.dumps(context.values, default=str),
            digest=file_digest(path),
        )
        # A history entry **without touching the pixels**: the script has already done its
        # work. This is a replayable marker, not one more transform.
        target.begin_process(repr(instance), process=instance)
        target.end_process()


# Shared application instance (importable anywhere: `from retina import app`)
app = Application()
