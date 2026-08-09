"""SafeLink unwrapping and tracking-param stripping for archived newsletters.

The markdown archive is a retrieval copy: URLs keep only their identity
(scheme/host/path/fragment plus the KEEP_PARAMS keeplist), never their
tracking payload.
"""

import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that carry link identity rather than tracking. Measured census
# of the real corpus (2026-08-09): only YouTube's `v` qualifies.
KEEP_PARAMS = frozenset({"v"})

_SAFELINK_HOST = re.compile(
    r"(^|\.)safelinks\.protection\.outlook\.com$", re.IGNORECASE
)


def _is_safelink(url: str) -> bool:
    return bool(_SAFELINK_HOST.search(urlsplit(url).netloc))


def clean_url(url: str) -> tuple[str, bool]:
    """Unwrap a SafeLink and strip tracking params.

    Returns (cleaned_url, unwrap_failed). On an unrecoverable SafeLink
    (missing url= param, or a destination that isn't http/https) the
    original URL is returned untouched with unwrap_failed=True.
    """
    if _is_safelink(url):
        target = parse_qs(urlsplit(url).query).get("url", [""])[0]
        if not target.startswith(("http://", "https://")):
            return url, True
        url = target

    parts = urlsplit(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k in KEEP_PARAMS
    ]
    url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )
    url = url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
    return url, False
