"""Color themes for the GHNoti TUI: one flat table, element -> string.

    [theme]
    unread   = "yellow bold"          # a color + format words
    title    = "white on blue bold"   # "on <color>" sets the background
    selected = "reverse bold"         # keep the terminal's own colors

Colors: "default" (whatever the terminal uses), the 8 curses names
("black"…"white"), their "bright-" variants, or hex "#rrggbb" / "#rgb" —
hex is matched to the nearest entry of the terminal's 256-color palette,
since curses has no truecolor API. Formats: bold, dim, reverse,
underline, italic, blink, standout. Unset keys fall back to
DEFAULTS, tuned for dark terminals; a terminal without (enough) color
support gets the same layout with the colors dropped.
"""

import curses
from collections import namedtuple

import config as cfg

# Colors as init_pair() wants them; -1 = the terminal's own color.
COLORS = {
    "default": -1,
    "black": curses.COLOR_BLACK,
    "red": curses.COLOR_RED,
    "green": curses.COLOR_GREEN,
    "yellow": curses.COLOR_YELLOW,
    "blue": curses.COLOR_BLUE,
    "magenta": curses.COLOR_MAGENTA,
    "cyan": curses.COLOR_CYAN,
    "white": curses.COLOR_WHITE,
    # The "bright" half of the usual 16-color palette.
    "bright-black": 8,
    "bright-red": 9,
    "bright-green": 10,
    "bright-yellow": 11,
    "bright-blue": 12,
    "bright-magenta": 13,
    "bright-cyan": 14,
    "bright-white": 15,
}

ATTRS = {
    "bold": curses.A_BOLD,
    "dim": curses.A_DIM,
    "reverse": curses.A_REVERSE,
    "underline": curses.A_UNDERLINE,
    "italic": getattr(curses, "A_ITALIC", 0),  # not in every ncurses build
    "blink": curses.A_BLINK,
    "standout": curses.A_STANDOUT,
}

# Every element the TUI renders; anything else under [theme] is a typo.
KEYS = (
    "background",  # base background of the whole screen
    "text",        # misc lines (the group-counts footer)
    "read",        # rows of read notifications
    "unread",      # rows of unread ones
    "selected",    # the row under the cursor
    "title",       # top bar + spinner
    "header",      # column labels
    "footer",      # key hints
    "empty",       # "(no notifications in this group)"
    "popup",       # error messages
)

DEFAULTS = {
    "background": "default",
    "text": "default",
    "read": "bright-black",  # greyed out, clearly dimmer than unread
    "unread": "default bold",
    "selected": "reverse bold",
    "title": "reverse bold",
    "header": "bold",
    "footer": "reverse",
    "empty": "dim",
    "popup": "reverse bold",
}

Spec = namedtuple("Spec", "fg bg attrs")  # bg None = inherit `background`


def _hex_color(tok: str) -> int | None:
    """#rgb / #rrggbb -> palette index 0-255, or None if malformed."""
    h = tok[1:]  # one leading '#' exactly, so '##fff' doesn't slip through
    if len(h) not in (3, 6) or not all(c in "0123456789abcdefABCDEF" for c in h):
        return None
    h = "".join(c * 2 for c in h) if len(h) == 3 else h  # #abc -> #aabbcc
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))

    # The 256-color palette: 16 named + 6x6x6 cube + 24 gray steps.
    # Pick the entry with the smallest squared RGB distance — good enough
    # for telling rows apart, which is all a 256-color scheme needs.
    def cube(i):  # cube level 0-5 -> terminal levels 0-255
        return [16, 116, 152, 178, 208, 232][i]

    best, dist = 0, 1 << 24
    for i in range(256):
        if i < 16:  # colors 0-15 aren't defined by any formula; skip them
            continue
        elif i < 232:
            j = i - 16
            ir, ig, ib = (cube(j // 36), cube(j // 6 % 6), cube(j % 6))
        else:
            ir = ig = ib = 8 + 10 * (i - 232)  # the gray ramp
        d = (r - ir) ** 2 + (g - ig) ** 2 + (b - ib) ** 2
        if d < dist:
            best, dist = i, d
    return best


def _color(tok: str) -> int | None:
    """Theme color word -> curses color number, None if it isn't one."""
    if tok in COLORS:
        return COLORS[tok]
    if tok.startswith("#") and len(tok) > 1:
        n = _hex_color(tok)
        if n is None:
            raise cfg.ConfigError(f"[theme] bad hex color '{tok}' (want #rgb or #rrggbb)")
        return n
    return None


def _parse(key: str, value) -> Spec:
    """One theme value -> Spec, raising ConfigError on unknown words.

    An empty or missing value means "terminal defaults, no formats".
    """
    if not isinstance(value, str):
        raise cfg.ConfigError(
            f"[theme.{key}] must be a string like 'yellow bold' or 'white on blue'"
        )
    fg, bg, attrs, waiting = -1, None, 0, False
    for tok in value.split():
        if waiting:
            c = _color(tok)
            if c is None:
                raise cfg.ConfigError(f"[theme.{key}] 'on' expects a color, not '{tok}'")
            bg, waiting = c, False
        elif tok == "on":
            waiting = True
        else:
            c = _color(tok)
            if c is not None:
                fg = c
            elif tok in ATTRS:
                attrs |= ATTRS[tok]
            else:
                raise cfg.ConfigError(
                    f"[theme.{key}] unknown '{tok}': a color is 'default', one of"
                    f" {', '.join(COLORS)}, '#rgb' or '#rrggbb'; formats are"
                    f" {', '.join(ATTRS)}"
                )
    if waiting:
        raise cfg.ConfigError(f"[theme.{key}] 'on' expects a following color")
    return Spec(fg, bg, attrs)


class Theme:
    """Parsed [theme] table; ``init(scr)`` turns it into curses attributes."""

    def __init__(self, table: dict):
        unknown = sorted(set(table) - set(KEYS))
        if unknown:
            raise cfg.ConfigError(
                f"[theme] has unknown key(s) {', '.join(unknown)}; valid: {', '.join(KEYS)}"
            )
        self.specs = {k: _parse(k, table.get(k, DEFAULTS[k])) for k in KEYS}
        base = self.specs["background"]
        if base.bg is not None or base.attrs:
            raise cfg.ConfigError("[theme.background] must be a single color name")
        self.background = base.fg
        self._attrs: dict[str, int] = {}

    def init(self, scr) -> None:
        """Build the color pairs; call once inside curses, before attr()."""
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            pass  # colorless terminal: attr() keeps just the format bits
        pairs: dict[tuple[int, int], int] = {}

        def pid(fg: int, bg: int) -> int:
            if (fg, bg) not in pairs:
                n = len(pairs) + 1
                try:
                    curses.init_pair(n, fg, bg)
                except (curses.error, ValueError):
                    # ValueError: colorless terminal (COLORS <= 0) or color
                    # out of range — drop just this color, keep the formats.
                    n = 0
                pairs[(fg, bg)] = n
            return pairs[(fg, bg)]

        self._attrs = {}
        for key, spec in self.specs.items():
            bg = self.background if spec.bg is None else spec.bg
            n = 0 if (spec.fg, bg) == (-1, -1) else pid(spec.fg, bg)
            self._attrs[key] = spec.attrs | (curses.color_pair(n) if n else 0)
        if self.background != -1:
            n = pid(-1, self.background)
            if n:
                scr.bkgd(" ", curses.color_pair(n))  # erase() repaints the bg

    def attr(self, key: str) -> int:
        """curses attribute (color pair | formats) for element `key`."""
        return self._attrs[key]