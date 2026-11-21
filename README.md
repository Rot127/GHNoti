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
    a                  toggle unread-only / include read (unread styled via [theme])
    D                  mark selected thread as Done (hidden everywhere)
    r                  re-fetch
    q                  quit

A failed or hung browser launch can't freeze or kill the TUI: the opener
is timeout-bounded and every keypress is wrapped in a catch-all.

Fetches run on a worker thread with a spinner in the title bar, so the
UI never freezes: navigation keeps working while data loads, and `a`/`r`/`m`
are deferred until the load finishes.

## Config (`~/.config/ghnoti/config.toml`)

    [groups.CoreTeam]
    authors = ["torvalds", "gregkh"]

    [groups.Kernel]
    repos = ["torvalds/linux"]           # authors and/or repos; both = AND

    [groups.React]
    repos = ["facebook/react"]
    authors = ["gaearon"]                # gaearon's notifications in react

    [theme]
    read     = "bright-black"            # any mix of color, "on <color>", formats
    unread   = "default bold"
    title    = "bold reverse"             # top bar, header, footer, popup, …
    selected = "bold reverse"

Groups are cycled with CTRL+h/CTRL+l; the built-in `__all__` group
shows every notification.

### Theme

`[theme]` is one flat table: element → style string. Elements:
`background`, `text`, `read`, `unread`, `selected`, `title`, `header`,
`footer`, `empty`, `popup`. A style is any mix of a color (`default`,
`black`…`white`, `bright-*`, or hex `#rgb`/`#rrggbb` — hex is snapped to
the nearest entry of the terminal's 256-color palette, since curses has
no truecolor API), `on <color>` for the background, and formats: `bold`,
`dim`, `reverse`, `underline`, `italic`, `blink`, `standout`. Unset
elements fall back to defaults tuned for dark terminals — `read` is grey
(`bright-black`) so it can't blur with `unread`. `background` (if set)
must be a single color name; a terminal without (enough) color support
keeps the layout, unrepresentable colors dropped.

## Security review

**`auth.py` is the only file that touches credentials.**
Lookup order: `gh auth token` → `$GH_NOTI_TOKEN` → `$GH_NOTI_TOKEN_FILE`
(default `~/.config/ghnoti/token`). The token is never logged or written.
If you audit one file, audit that one.
