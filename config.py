"""Config loading for GHNoti: groups -> author lists, defined in TOML."""

import tomllib
from pathlib import Path

# Keep one canonical layout even if the user drops a config somewhere else.
DEFAULT_CONFIG = Path("~/.config/ghnoti/config.toml").expanduser()
FALLBACK_CONFIG = Path(__file__).with_suffix(".toml")


class ConfigError(RuntimeError):
    """Raised when the config file is missing or malformed."""


def load(path: str | Path | None = None) -> dict:
    """Return ``{"groups": [{"name", "authors", "repos"}]}``.

    Each group filters by ``authors`` (GitHub logins) and/or ``repos``
    (full names like ``owner/repo``); when both are given a notification
    must match BOTH. Values are stored lowercased; ``None`` means "no
    filter". A special group ``__all__`` (always first) shows every
    notification; it is generated, not configured.
    """
    path = Path(path).expanduser() if path else DEFAULT_CONFIG
    if not path.exists():
        path = FALLBACK_CONFIG
    try:
        raw = tomllib.loads(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"bad TOML in {path}: {exc}") from exc

    groups = []
    for name, table in (raw.get("groups") or {}).items():
        if not isinstance(table, dict):
            raise ConfigError(f"[groups.{name}] must be a table of 'authors' and/or 'repos'")
        if name == "__all__":
            raise ConfigError("[groups.__all__] is reserved")
        group = {"name": name, "authors": None, "repos": None}
        for key in ("authors", "repos"):
            values = table.get(key, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ConfigError(f"[groups.{name}] '{key}' must be a list of strings")
            values = {v.strip().lower() for v in values} - {""}
            group[key] = values or None
        if group["authors"] is None and group["repos"] is None:
            raise ConfigError(f"[groups.{name}] needs a non-empty 'authors' and/or 'repos' list")
        groups.append(group)

    groups.sort(key=lambda g: g["name"])
    # "__all__" is reserved: every notification, no filters.
    groups.insert(0, {"name": "__all__", "authors": None, "repos": None})
    return {"groups": groups}
