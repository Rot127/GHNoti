"""GitHub REST API access.

No secrets are *read* here: ``make_session`` receives the token already
loaded by ``auth.load_token()`` (auth.py is the credential choke point)
and stores it in the session's Authorization header. Every request in
this module goes through that session, so every call is authenticated
and the token never appears in urls, params, or logs.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import requests

# Base URL of the GitHub REST API — a URL, not a credential. Override for
# GitHub Enterprise (…/api/v3) or a local stub server.
API_URL = os.environ.get("GH_NOTI_API_URL", "https://api.github.com")


def make_session(token: str) -> requests.Session:
    """Return a session whose every request carries the token."""
    session = requests.Session()
    # The token rides in this header; the functions below only ever touch
    # the session, never the token.
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ghnoti",
        }
    )
    return session


def fetch_notifications(
    session: requests.Session, show_all: bool = False, max_pages: int = 10
) -> list[dict]:
    """Fetch the authenticated user's notifications (GET /notifications)."""
    out: list[dict] = []
    url, params = f"{API_URL}/notifications", {"per_page": 100, "all": str(show_all).lower()}
    for _ in range(max_pages):
        r = session.get(url, params=params, timeout=15)
        r.raise_for_status()
        batch = r.json()
        out.extend(batch)
        url, params = r.links.get("next", {}).get("url"), None
        if not url or not batch:
            break
    return out


def mark_read(session: requests.Session, thread_id: str) -> None:
    """Mark one notification thread as read (PATCH /notifications/threads/{id})."""
    r = session.patch(
        f"{API_URL}/notifications/threads/{thread_id}", timeout=15
    )
    if r.status_code not in (202, 205):
        r.raise_for_status()


def enrich(session: requests.Session, notes: list[dict], workers: int = 10) -> None:
    """Resolve ``(author, html_url)`` for every notification subject, in place.

    The notifications payload carries no author, so one extra request per
    *unique* subject URL is required; they are fetched concurrently through
    the authenticated session.
    """
    urls = {n["subject"].get("url") for n in notes} - {None}

    def lookup(url: str):
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                return None, None
            j = r.json()
            author = (j.get("user") or j.get("author") or {}).get("login")
            return author, j.get("html_url")
        except requests.RequestException:
            return None, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        info = dict(zip(urls, ex.map(lookup, urls)))
    for n in notes:
        n["author"], n["html_url"] = info.get(n["subject"].get("url"), (None, None))
