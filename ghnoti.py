#!/usr/bin/env python3
"""GHNoti — browse GitHub notifications, grouped by author.

Usage:
    python3 ghnoti.py [--config PATH] [--all]

    Credentials are handled exclusively by auth.py — see the review
    banner at the top of that file.

Keys:
    CTRL+h / CTRL+l   previous / next group (wraps; plain h/l also work)
    j / k (or ↑ / ↓)  move selection
    ENTER             open the selected notification in the browser
    m                 mark the selected thread as read (on GitHub)
    a                 toggle unread-only / include read (unread = bold)
    r                 re-fetch notifications
    D                 mark selected thread as Done (removes it everywhere)
    q                 quit

While data is loading a spinner runs in the title bar; j/k and group
cycling still work, but a/r/m are ignored until the load finishes.
"""

import argparse
import curses
import datetime as dt
import os
import shlex
import subprocess
import threading
import time
import webbrowser

import auth
import config as cfg
import github_api as gapi

DATE_FMT = "%d %b %H:%M"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"  # ~12 frames/sec
TYPE_NAMES = {
    "PullRequest": "PR",
    "Issue": "ISSUE",
    "Release": "REL",
    "Discussion": "DISC",
}


# ─── state ─────────────────────────────────────────────────────────────


def repo_name(n: dict) -> str:
    """Full repo name ("owner/repo") from a notification's repository block.

    The API may give ``full_name`` directly or only ``repo_url``/``html_url``,
    in which case the last two URL path segments are the full name.
    """
    repo = n.get("repository") or {}
    name = repo.get("full_name")
    if not name:
        url = repo.get("repo_url") or repo.get("html_url") or ""
        name = "/".join(url.rstrip("/").split("/")[-2:])
    return name.strip("/")


def matches(n: dict, group: dict) -> bool:
    """True if notification `n` passes the group's author and/or repo filter.

    A configured group has ``authors`` and/or ``repos`` (``None`` = no
    filter); when both are set, a notification must match BOTH.
    """
    if group["authors"] is not None and (n.get("author") or "").lower() not in group["authors"]:
        return False
    if group["repos"] is not None and repo_name(n).lower() not in group["repos"]:
        return False
    return True


class State:
    """Everything the TUI renders: notes, current group, per-group cursors."""

    def __init__(self, groups: list[dict], notes: list[dict], show_all: bool = False):
        self.groups = groups
        self.notes = notes
        self.show_all = show_all  # False = unread only; toggled with 'a'
        self.group = 0  # __all__ is always first
        self.cursor: dict[int, int] = {}  # group index -> selected row
        self.scroll = 0

    def visible(self) -> list[dict]:
        group = self.groups[self.group]
        rows = [n for n in self.notes if matches(n, group)]
        rows.sort(key=lambda n: n.get("updated_at") or "", reverse=True)
        return rows

    def row(self) -> int:
        return self.cursor.get(self.group, 0)

    def move(self, d: int) -> None:
        rows = self.visible()
        if rows:
            self.cursor[self.group] = min(max(self.row() + d, 0), len(rows) - 1)

    def step_group(self, d: int) -> None:
        self.group = (self.group + d) % len(self.groups)
        self.move(0)

    def selected(self) -> dict | None:
        rows = self.visible()
        return rows[self.row()] if rows else None


# ─── helpers ────────────────────────────────────────────────────────────


def put(scr, y: int, x: int, text: str, attr: int = 0) -> None:
    """addstr that tolerates the bottom-right corner and tiny terminals."""
    maxy, maxx = scr.getmaxyx()
    if 0 <= y < maxy and x < maxx:
        try:
            scr.addstr(y, x, text[: max(1, maxx - x - 1)], attr)
        except curses.error:
            pass


def popup(scr, lines: list[str]) -> None:
    """Blocking centered message; any key dismisses."""
    scr.timeout(-1)  # block for the key even if the event loop is in poll mode
    scr.erase()
    maxy, maxx = scr.getmaxyx()
    for i, text in enumerate(lines[: max(1, maxy - 2)]):
        put(scr, maxy // 2 - len(lines) // 2 + i, 2, f" {text} ", curses.A_REVERSE)
    scr.refresh()
    scr.getch()


def fmt_row(n: dict) -> str:
    when = n.get("updated_at") or ""
    try:
        when = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
        when = when.astimezone().strftime(DATE_FMT)
    except ValueError:
        when = "?" * len(DATE_FMT)
    author = (n.get("author") or "?")[:12]
    typ = TYPE_NAMES.get(n["subject"].get("type"), "?")
    repo = repo_name(n)
    return f"{when:<12}  {author:<12}  {typ:<5}  {repo:<30}  {n['subject'].get('title', '')}"


XDG_OPEN_TIMEOUT = 20  # seconds; a hung opener must not freeze the TUI


def open_in_browser(url: str) -> str | None:
    """Open `url` in a browser; return an error string, or None on success.

    Order: $BROWSER (console command, runs in the foreground), then
    `xdg-open`, then Python's webbrowser as a last resort. Never raises
    and never hangs longer than XDG_OPEN_TIMEOUT — the caller must stay
    in control of the terminal. Must be called with curses suspended.
    """
    browser = os.environ.get("BROWSER")
    if browser:
        try:
            if subprocess.run(shlex.split(browser) + [url]).returncode == 0:
                return None
        except (OSError, ValueError):
            pass
    try:
        if subprocess.run(
            ["xdg-open", url], timeout=XDG_OPEN_TIMEOUT, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return None
    except (OSError, subprocess.SubprocessError):
        pass  # no xdg-open, or it hung / failed
    try:
        if webbrowser.open(url):
            return None
    except webbrowser.Error:
        pass
    return f"could not open browser for {url}"


class Loader:
    """Run a fetch on a worker thread so the TUI can keep drawing.

    ``done`` flips to True once ``result`` (or ``error``) is available;
    the event loop polls it and shows a spinner in the meantime.
    """

    def __init__(self, fn, *args):
        self.result = None
        self.error = None
        self.done = False
        self.thread = threading.Thread(target=self._run, args=(fn, args), daemon=True)
        self.thread.start()

    def _run(self, fn, args):
        try:
            self.result = fn(*args)
        except Exception as exc:  # surfaced to the user by the event loop
            self.error = exc
        self.done = True


# ─── drawing ────────────────────────────────────────────────────────────


def draw(scr, state: State, loading: Loader | None = None) -> None:
    scr.erase()
    maxy, maxx = scr.getmaxyx()
    rows = state.visible()
    state.move(0)  # clamp cursor when the list shrank under it

    group = state.groups[state.group]
    put(
        scr, 0, 0,
        f" GHNoti — {group['name']}  ({state.group + 1}/{len(state.groups)})  "
        f"{len(rows)} notifications{' (incl. read)' if state.show_all else ''} ",
        curses.A_REVERSE | curses.A_BOLD,
    )
    if loading is not None:
        frame = SPINNER[int(time.monotonic() * 12) % len(SPINNER)]
        put(scr, 0, max(0, maxx - 4), f" {frame} ", curses.A_REVERSE | curses.A_BOLD)
    put(scr, 1, 0, f" {'DATE':<12}  {'AUTHOR':<12}  {'TYPE':<5}  {'REPOSITORY':<30}  TITLE", curses.A_BOLD)

    top, height = 2, max(0, maxy - 4)
    cur = state.row()
    state.scroll = min(max(state.scroll, cur - height + 1), max(0, cur))
    for i, n in enumerate(rows[state.scroll : state.scroll + height]):
        attr = curses.A_REVERSE if state.scroll + i == cur else 0
        if n.get("unread"):
            attr |= curses.A_BOLD
        put(scr, top + i, 0, " " + fmt_row(n), attr)
    if not rows:
        put(scr, top, 2, "(no notifications in this group)", curses.A_DIM)

    put(
        scr, maxy - 2, 0,
        " ^h/^l group  j/k move  ENTER open  m read  D done  a unread/all  r refresh  q quit ",
        curses.A_REVERSE,
    )
    counts = [
        f" {g['name']}({sum(1 for n in state.notes if matches(n, g))})"
        for g in state.groups
    ]
    put(scr, maxy - 1, 0, " groups:" + "".join(counts))
    scr.refresh()


# ─── event loop ─────────────────────────────────────────────────────────


def run(scr, state: State, session) -> None:
    def start_refresh() -> Loader:
        """Fetch + enrich on a worker thread; result is the new notes list."""

        def load():
            notes = gapi.fetch_notifications(session, show_all=state.show_all)
            gapi.enrich(session, notes)
            return notes

        return Loader(load)

    curses.curs_set(0)
    loading: Loader | None = start_refresh()  # initial load, spinner visible
    pending_toggle = False  # a load started by the 'a' key (rolls back on error)
    while True:
        scr.timeout(80 if loading else -1)  # poll while loading: animate the spinner
        draw(scr, state, loading)
        ch = scr.getch()

        if loading is not None and loading.done:  # adopt the finished load
            done, loading = loading, None
            scr.timeout(-1)
            try:
                if done.error is not None:
                    raise done.error
                state.notes = done.result
            except Exception as exc:
                if pending_toggle:  # 'a' flipped the flag already: undo it
                    state.show_all = not state.show_all
                popup(scr, [f"{'toggle' if pending_toggle else 'refresh'} failed: {exc}"])
            finally:
                pending_toggle = False

        try:
            if ch in (ord("q"), 27):
                return
            elif ch in (curses.KEY_ENTER, 10, 13):
                n = state.selected()
                url = n and (n.get("html_url") or n.get("repository", {}).get("repo_url"))
                if url:
                    curses.endwin()  # leave the alternate screen while the browser runs
                    err = open_in_browser(url)
                    scr.refresh()
                    if err:
                        popup(scr, [err])
            elif ch in (ord("j"), curses.KEY_DOWN):
                state.move(1)
            elif ch in (ord("k"), curses.KEY_UP):
                state.move(-1)
            elif ch in (8, ord("h")):  # CTRL+h (some terminals send plain h-safe code)
                state.step_group(-1)
            elif ch in (12, ord("l")):  # CTRL+l
                state.step_group(1)
            elif ch == ord("m") and loading is None:
                n = state.selected()
                if n:
                    try:
                        gapi.mark_read(session, n["id"])
                        if state.show_all:
                            n["unread"] = False  # keep it listed, just un-bold it
                        else:
                            state.notes.remove(n)
                    except Exception as exc:
                        popup(scr, [f"mark-as-read failed: {exc}"])
            elif ch == ord("D") and loading is None:  # mark Done: gone in every mode
                n = state.selected()
                if n:
                    try:
                        gapi.mark_done(session, n["id"])
                        state.notes.remove(n)
                    except Exception as exc:
                        popup(scr, [f"mark-as-done failed: {exc}"])
            elif ch == ord("a") and loading is None:  # toggle unread-only <-> read
                state.show_all = not state.show_all
                pending_toggle = True
                loading = start_refresh()
            elif ch == ord("r") and loading is None:
                loading = start_refresh()
        except Exception as exc:  # never let one bad key kill the whole TUI
            curses.endwin()
            popup(scr, [f"error: {exc}"])


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub notifications, grouped by author.")
    parser.add_argument("--config", help="config file (default: ~/.config/ghnoti/config.toml)")
    parser.add_argument("--all", action="store_true", help="also show notifications marked as read")
    args = parser.parse_args()

    token = auth.load_token()  # ← the only secrets touchpoint; see auth.py
    session = gapi.make_session(token)
    groups = cfg.load(args.config)["groups"]
    # Notes load inside the TUI so the very first fetch shows the spinner too.
    state = State(groups, [], show_all=args.all)
    curses.wrapper(run, state, session)


if __name__ == "__main__":
    main()
