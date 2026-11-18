"""Credential handling for GHNoti.

┌─────────────────────────────────────────────────────────────────────┐
│  ★ SECRETS-REVIEW ZONE ★                                            │
│  This is the ONLY file in the project that reads your GitHub token. │
│  Nothing else touches credentials; audit this file with extra care. │
└─────────────────────────────────────────────────────────────────────┘

Token lookup order:
    1. `gh` CLI             `gh auth token` (gh's own stored credential)
    2. $GH_NOTI_TOKEN       environment variable
    3. $GH_NOTI_TOKEN_FILE  file containing the token
       (default: ~/.config/ghnoti/token)

The token is returned as a plain string and handed to
github_api.make_session() by ghnoti.py. It is never logged, printed,
or written anywhere.
"""

import os
import shutil
import subprocess
from pathlib import Path

TOKEN_ENV = "GH_NOTI_TOKEN"        # ← credential source 2: environment variable
TOKEN_FILE_ENV = "GH_NOTI_TOKEN_FILE"                              # ← source 3
DEFAULT_TOKEN_FILE = Path("~/.config/ghnoti/token").expanduser()   # ← default path


class TokenError(RuntimeError):
    """Raised when no usable GitHub token could be loaded."""


def _token_from_gh() -> str | None:
    """Ask the `gh` CLI for the token it has stored (`gh auth token`)."""
    if not shutil.which("gh"):                       # gh not installed
        return None
    try:
        # capture_output keeps the token off the terminal; it must never
        # be echoed, logged, or written anywhere.
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:                          # gh installed but not logged in
        return None
    return out.stdout.strip() or None


def load_token() -> str:
    """Return the GitHub personal access token.

    ★ This function is the single choke point for secret access. ★
    """
    token = _token_from_gh()                          # ← credential source 1: gh CLI
    if token:
        return token

    token = os.environ.get(TOKEN_ENV, "").strip()     # ← source 2: environment variable
    if token:
        return token

    path = Path(os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE).expanduser()
    try:
        token = path.read_text().strip()              # ← source 3: credential file on disk
    except OSError as exc:
        raise TokenError(
            f"no GitHub token found: log in with `gh auth login`, "
            f"set ${TOKEN_ENV}, or put a token in {path} ({exc})"
        ) from exc
    if not token:
        raise TokenError(f"token file {path} is empty")
    return token
