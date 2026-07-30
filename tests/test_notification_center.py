"""Notification center: pure domain, bounded, thread-safe, echoed where it should be.

Console/GUI parity requires that everything the interface's bell shows be readable and
dismissible from the console (``app.notifications``) — these tests check that without the
shell.
"""

from __future__ import annotations

import threading

from retina.notifications import NotificationCenter


def _center(echoes: list[str] | None = None) -> NotificationCenter:
    return NotificationCenter((echoes if echoes is not None else []).append)


def test_add_and_read() -> None:
    center = _center()
    note = center.add("disk full", kind="error", source="Integration")
    assert note.id == "n1"
    assert note.kind == "error"
    assert note.timestamp > 0
    second = center.add("info")
    assert second.id == "n2"
    # most recent first, iterable and measurable like a list
    assert [n.id for n in center] == ["n2", "n1"]
    assert len(center) == 2
    assert center.all()[0].to_dict()["message"] == "info"


def test_invalid_kind() -> None:
    center = _center()
    try:
        center.add("x", kind="fatal")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown kind accepted")


def test_max_bound() -> None:
    center = _center()
    for i in range(NotificationCenter.MAX + 10):
        center.add(f"m{i}")
    assert len(center) == NotificationCenter.MAX
    # the most recent ones are the survivors
    assert center.all()[0].message == f"m{NotificationCenter.MAX + 9}"


def test_dismiss_and_clear_echo() -> None:
    echoes: list[str] = []
    center = _center(echoes)
    note = center.add("a")  # add does not echo: it is not a user gesture
    assert echoes == []
    assert center.dismiss(note.id) is True
    assert center.dismiss("n999") is False
    center.clear()
    assert echoes == [
        f"app.notifications.dismiss({note.id!r})",
        "app.notifications.dismiss('n999')",
        "app.notifications.clear()",
    ]
    assert len(center) == 0


def test_on_changed() -> None:
    events: list[tuple[str, dict]] = []
    center = _center()
    center.on_changed = lambda event, payload: events.append((event, payload))
    note = center.add("boom", kind="warning", source="script")
    center.dismiss(note.id)
    center.dismiss(note.id)  # already gone: no event
    center.clear()
    assert [e for e, _ in events] == ["added", "dismissed", "cleared"]
    assert events[0][1]["message"] == "boom"
    assert events[0][1]["source"] == "script"
    assert events[1][1] == {"id": note.id}


def test_add_concurrent() -> None:
    center = _center()

    def push() -> None:
        for _ in range(200):
            center.add("x")

    threads = [threading.Thread(target=push) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # the bound holds under concurrency, and the ids stay unique
    assert len(center) == NotificationCenter.MAX
    ids = [n.id for n in center]
    assert len(ids) == len(set(ids))


def test_app_notify() -> None:
    from retina import app

    before = len(app.notifications)
    echoes: list[str] = []
    previous = app.on_echo
    app.on_echo = echoes.append
    try:
        note = app.notify("Masters ready", source="recipe")
        assert note.kind == "info"
        assert len(app.notifications) == before + 1
        assert echoes == []  # notify does not echo either
    finally:
        app.on_echo = previous
        app.notifications.dismiss(note.id)
