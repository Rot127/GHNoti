# GHNoti

Terminal UI for your GitHub notifications, grouped by author and/or repo.

Useful to get some priority in the ever growing notification list.

> [!NOTE]
> Everything is vibe coded and of "works-for-me" quality.
> I won't maintain it above that.
> Tested on Fedora.

## Run

    python3 ghnoti.py [--config PATH] [--all]

Needs `requests` (nothing else) and Python ≥ 3.11.

## Keys

    CTRL+h / CTRL+l   previous / next group (wraps around)
    j / k, ↑ / ↓      move selection
    ENTER              open notification in browser ($BROWSER, then xdg-open)
    m                  mark selected thread as read
    a                  toggle unread-only / include read (unread = bold)
    r                  re-fetch
    q                  quit

A failed or hung browser launch can't freeze or kill the TUI: the opener
is timeout-bounded and every keypress is wrapped in a catch-all.

## Config (`~/.config/ghnoti/config.toml`)

    [groups.CoreTeam]
    authors = ["torvalds", "gregkh"]

    [groups.Kernel]
    repos = ["torvalds/linux"]           # authors and/or repos; both = AND

    [groups.React]
    repos = ["facebook/react"]
    authors = ["gaearon"]                # gaearon's notifications in react

Groups are cycled with CTRL+h/CTRL+l; the built-in `__all__` group
shows every notification.

## Security review

**`auth.py` is the only file that touches credentials.**
Lookup order: `gh auth token` → `$GH_NOTI_TOKEN` → `$GH_NOTI_TOKEN_FILE`
(default `~/.config/ghnoti/token`). The token is never logged or written.
If you audit one file, audit that one.
