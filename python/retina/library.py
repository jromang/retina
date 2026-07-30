"""Library of recipes and process instances, named and persistent.

**Named** process instances and pipelines (:class:`ProcessContainer`), persistent on disk
(one XML file per entry), addressable from the console:

    app.library['M31 background'] = DynamicBackgroundExtraction(samples=[...])
    app.library['M31 recipe'] = app.active_view.recipe()
    app.library['M31 background'].execute_on(app.active_view)

Storage: ``$RETINA_CONFIG_DIR/library/`` if the variable is set (tests), otherwise
``%APPDATA%/retina/library`` (Windows) or ``$XDG_CONFIG_HOME|~/.config/retina/library``.
Every entry carries an optional (x, y) position — the GUI's "Desktop" surface (freely
arranged icons, workspace style) is simply one more view of it.
"""

from __future__ import annotations

import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator

from .i18n import translate as _t
from .paths import config_path
from .process.base import Process
from .process.container import (
    ProcessContainer,
    container_from_elements,
    container_to_elements,
    process_from_element,
    process_to_element,
)


def _default_root() -> str:
    return str(config_path("library"))


def _slug(name: str) -> str:
    folded = (unicodedata.normalize("NFKD", name)
              .encode("ascii", "ignore").decode("ascii").lower())
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "item"


class Library:
    """Persistent dict-like: ``app.library[name]`` ↔ an XML on disk."""

    def __init__(self, root_dir: str | None = None,
                 echo: Callable[[str], None] | None = None) -> None:
        self._root = root_dir or _default_root()
        self._echo = echo or (lambda code: None)
        #: GUI hook: called after any mutation (Library panel + Desktop)
        self.on_changed: Callable[[], None] | None = None

    # --- index ----------------------------------------------------------------
    def _scan(self) -> dict[str, str]:
        """``{name: path}`` — re-reads the disk (few files, the source of truth)."""
        out: dict[str, str] = {}
        if not os.path.isdir(self._root):
            return out
        for fn in sorted(os.listdir(self._root)):
            if not fn.endswith(".xml"):
                continue
            path = os.path.join(self._root, fn)
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            name = root.get("name") or os.path.splitext(fn)[0]
            out[name] = path
        return out

    def names(self) -> list[str]:
        return list(self._scan())

    def __iter__(self) -> Iterator[str]:
        return iter(self._scan())

    def __len__(self) -> int:
        return len(self._scan())

    def __contains__(self, name: str) -> bool:
        return name in self._scan()

    def _path_of(self, name: str) -> str:
        path = self._scan().get(name)
        if path is None:
            raise KeyError(_t("Unknown library entry: {name!r}").format(name=name))
        return path

    def _new_path(self, name: str) -> str:
        os.makedirs(self._root, exist_ok=True)
        slug = _slug(name)
        path = os.path.join(self._root, f"{slug}.xml")
        n = 1
        taken = set(self._scan().values())
        while path in taken:
            n += 1
            path = os.path.join(self._root, f"{slug}-{n}.xml")
        return path

    # --- dict-like access -----------------------------------------------------
    def __setitem__(self, name: str, item: Process | ProcessContainer) -> None:
        if not isinstance(item, (Process, ProcessContainer)):
            raise TypeError(
                _t("app.library accepts a configured Process or a ProcessContainer."))
        try:
            path = self._path_of(name)  # replaces while keeping position/file
            old = ET.parse(path).getroot()
            pos = (old.get("x"), old.get("y"))
        except KeyError:
            path = self._new_path(name)
            pos = (None, None)
        kind = "container" if isinstance(item, ProcessContainer) else "instance"
        root = ET.Element("library-item", {"name": name, "kind": kind})
        if pos[0] is not None:
            root.set("x", pos[0])
            root.set("y", pos[1] or "0")
        if isinstance(item, ProcessContainer):
            # Writing delegated to the container: it carries the disabled steps and their
            # masks. Rewriting the loop here lost them — the file read back returned a
            # recipe that looked identical, but whose flags had all fallen back.
            container_to_elements(item, root)
        else:
            process_to_element(item, root)
        ET.indent(root, space="  ")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ET.tostring(root, encoding="unicode"))
        self._echo(f"app.library[{name!r}] = {item!r}")
        self._notify()

    def __getitem__(self, name: str) -> Process | ProcessContainer:
        root = ET.parse(self._path_of(name)).getroot()
        elements = root.findall("process")
        if root.get("kind") == "container" or root.tag == "recipe" or len(elements) != 1:
            return container_from_elements(root)
        return process_from_element(elements[0])

    def __delitem__(self, name: str) -> None:
        os.remove(self._path_of(name))
        self._echo(f"del app.library[{name!r}]")
        self._notify()

    def kind(self, name: str) -> str:
        root = ET.parse(self._path_of(name)).getroot()
        if root.get("kind"):
            return root.get("kind")
        return "container" if len(root.findall("process")) != 1 else "instance"

    def rename(self, old: str, new: str) -> None:
        new = new.strip()
        if not new:
            raise ValueError(_t("Empty name."))
        if new in self:
            raise ValueError(_t("Name already taken: {name!r}").format(name=new))
        path = self._path_of(old)
        tree = ET.parse(path)
        tree.getroot().set("name", new)
        tree.write(path, encoding="unicode")
        self._echo(f"app.library.rename({old!r}, {new!r})")
        self._notify()

    # --- positions ("Desktop" surface) ----------------------------------------
    def move(self, name: str, x: float, y: float) -> None:
        path = self._path_of(name)
        tree = ET.parse(path)
        tree.getroot().set("x", repr(float(x)))
        tree.getroot().set("y", repr(float(y)))
        tree.write(path, encoding="unicode")
        self._echo(f"app.library.move({name!r}, {float(x)!r}, {float(y)!r})")
        self._notify()

    def position(self, name: str) -> tuple[float, float] | None:
        root = ET.parse(self._path_of(name)).getroot()
        if root.get("x") is None:
            return None
        return (float(root.get("x")), float(root.get("y") or 0.0))

    def _notify(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def __repr__(self) -> str:
        return f"Library({self._root!r}, {len(self)} entries)"
