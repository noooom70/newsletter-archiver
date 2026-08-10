# Retrieval-Grade Extraction + Regenerate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the archiver's markdown output a clean retrieval copy (SafeLinks unwrapped, tracking params stripped, chrome and layout tables removed, meaningful alt text kept) and add a `regenerate` command that rebuilds all existing `.md` files from stored `.html`.

**Architecture:** A new pure-URL module `fetcher/link_cleaner.py` handles SafeLink unwrapping and param stripping; `fetcher/content_extractor.py` gains tree-level stages (chrome/boilerplate removal, alt-text preservation, layout-table flattening) composed into `extract_markdown()`. A new `storage/regenerator.py` walks the archive, regenerates bodies while preserving frontmatter verbatim, and updates DB metrics (updates only, never inserts). A thin Typer command wires it up.

**Tech Stack:** Python 3.11+, Poetry (NOT uv), BeautifulSoup4, markdownify, Typer, SQLAlchemy, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-09-retrieval-grade-extraction-design.md` — read it first.

## Global Constraints

- Run everything with `poetry run ...` (Poetry project — never `uv run`).
- `.html` archive files are NEVER opened for writing anywhere in the code path.
- Tracking-param keeplist is exactly `KEEP_PARAMS = {"v"}`.
- The repo is PUBLIC. No real email addresses, no real tokens/JWTs, and no raw copies of archived newsletters may be committed. Fixtures use `reader@example.com` and clearly synthetic token values. A leak-check test enforces this.
- Public API compatibility: `html_to_markdown(html) -> str` and `build_markdown_document(...)` keep their signatures; existing tests must keep passing.
- DB: `regenerate` may UPDATE existing Newsletter rows (word_count, reading_time_minutes) matched by `markdown_path`; it must never INSERT rows.
- Lint gate: `poetry run ruff check .` must pass before every commit.
- Work on branch `feature/retrieval-grade-extraction` (already created; spec is committed there).

---

### Task 1: URL cleaning — `clean_url()` in a new `link_cleaner` module

**Files:**
- Create: `src/newsletter_archiver/fetcher/link_cleaner.py`
- Test: `tests/test_link_cleaner.py` (new)

**Interfaces:**
- Produces: `clean_url(url: str) -> tuple[str, bool]` — returns `(cleaned_url, unwrap_failed)`. Unwraps a SafeLink to its `url=` destination (single decode via `parse_qs`), then strips every query param not in `KEEP_PARAMS = {"v"}` from ANY url, keeps the fragment, and percent-encodes `(` → `%28`, `)` → `%29`, and space → `%20` so the URL can't break markdown link syntax (parens as a pair for visual consistency). `unwrap_failed` is True only when the input was a SafeLink whose destination could not be recovered (missing `url=` param or non-http(s) destination); the original URL is returned in that case (still param-stripped is NOT applied to unrecoverable safelinks — return the original untouched so nothing is corrupted).
- Produces: `KEEP_PARAMS: frozenset[str]` module constant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_link_cleaner.py
"""Tests for SafeLink unwrapping and tracking-param stripping."""

from newsletter_archiver.fetcher.link_cleaner import clean_url

SAFELINK = (
    "https://na01.safelinks.protection.outlook.com/?url="
    "https%3A%2F%2Fstratechery.com%2F2026%2Fexample-article%2F"
    "%3Faccess_token%3DSYNTH.TOKEN.VALUE"
    "&data=05%7C02%7CSYNTHDATA&sdata=SYNTHSIG&reserved=0"
)


def test_clean_url_unwraps_safelink():
    url, failed = clean_url(SAFELINK)
    assert url == "https://stratechery.com/2026/example-article/"
    assert failed is False


def test_clean_url_strips_tracking_params_from_plain_url():
    url, failed = clean_url(
        "https://click.e.economist.com/u/?qs=SYNTHTRACKER&m=123"
    )
    assert url == "https://click.e.economist.com/u/"
    assert failed is False


def test_clean_url_keeps_youtube_v_param():
    url, _ = clean_url("https://www.youtube.com/watch?v=abc123&si=TRACK")
    assert url == "https://www.youtube.com/watch?v=abc123"


def test_clean_url_keeps_fragment():
    url, _ = clean_url("https://example.com/page?utm_source=x#section-2")
    assert url == "https://example.com/page#section-2"


def test_clean_url_safelink_missing_url_param_fails_open():
    original = "https://na01.safelinks.protection.outlook.com/?data=05%7C02"
    url, failed = clean_url(original)
    assert url == original
    assert failed is True


def test_clean_url_safelink_non_http_destination_fails_open():
    original = (
        "https://na01.safelinks.protection.outlook.com/?url=javascript%3Aalert(1)"
    )
    url, failed = clean_url(original)
    assert url == original
    assert failed is True


def test_clean_url_nested_redirect_unwraps_one_level_only():
    # Outer SafeLink unwraps; the publisher's own ?url= redirect param is a
    # tracking-strippable param (not in keeplist), so it gets stripped.
    wrapped = (
        "https://na01.safelinks.protection.outlook.com/?url="
        "https%3A%2F%2Fpublisher.example%2Fredirect%3Furl%3Dhttps%253A%252F%252Ffinal.example"
    )
    url, failed = clean_url(wrapped)
    assert url == "https://publisher.example/redirect"
    assert failed is False


def test_clean_url_encodes_markdown_breaking_chars():
    url, _ = clean_url("https://en.wikipedia.org/wiki/Foo_(bar)")
    assert url == "https://en.wikipedia.org/wiki/Foo_%28bar%29"


def test_clean_url_plain_url_without_query_untouched():
    url, failed = clean_url("https://example.com/article")
    assert url == "https://example.com/article"
    assert failed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_link_cleaner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'newsletter_archiver.fetcher.link_cleaner'`

- [ ] **Step 3: Write the implementation**

```python
# src/newsletter_archiver/fetcher/link_cleaner.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_link_cleaner.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/fetcher/link_cleaner.py tests/test_link_cleaner.py
git commit -m "feat: add link_cleaner with SafeLink unwrap and tracking-param strip"
```

---

### Task 2: Tree-level link cleaning — `clean_links(soup)`

**Files:**
- Modify: `src/newsletter_archiver/fetcher/link_cleaner.py`
- Test: `tests/test_link_cleaner.py`

**Interfaces:**
- Consumes: `clean_url` (Task 1).
- Produces: `clean_links(soup: BeautifulSoup) -> int` — rewrites the `href` of every `<a href=...>` in the tree via `clean_url`, returns the count of unwrap failures. Anchors without `href` are ignored.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_link_cleaner.py`)

```python
from bs4 import BeautifulSoup

from newsletter_archiver.fetcher.link_cleaner import clean_links


def test_clean_links_rewrites_all_hrefs():
    soup = BeautifulSoup(
        f'<p><a href="{SAFELINK}">Read</a>'
        '<a href="https://x.example/a?qs=T">Other</a>'
        "<a>no href</a></p>",
        "html.parser",
    )
    failures = clean_links(soup)
    assert failures == 0
    hrefs = [a.get("href") for a in soup.find_all("a")]
    assert hrefs[0] == "https://stratechery.com/2026/example-article/"
    assert hrefs[1] == "https://x.example/a"
    assert hrefs[2] is None


def test_clean_links_counts_unwrap_failures():
    bad = "https://na01.safelinks.protection.outlook.com/?data=05"
    soup = BeautifulSoup(f'<a href="{bad}">x</a>', "html.parser")
    assert clean_links(soup) == 1
    assert soup.find("a")["href"] == bad
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_link_cleaner.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'clean_links'`

- [ ] **Step 3: Write the implementation** (append to `link_cleaner.py`)

```python
def clean_links(soup) -> int:
    """Clean every anchor href in place. Returns the unwrap-failure count."""
    failures = 0
    for a in soup.find_all("a", href=True):
        cleaned, failed = clean_url(a["href"])
        a["href"] = cleaned
        failures += int(failed)
    return failures
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_link_cleaner.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/fetcher/link_cleaner.py tests/test_link_cleaner.py
git commit -m "feat: add clean_links tree pass over anchor hrefs"
```

---

### Task 3: Extended chrome and boilerplate removal

**Files:**
- Modify: `src/newsletter_archiver/fetcher/content_extractor.py` (the `clean_html` footer_patterns block, ~lines 32-51)
- Test: `tests/test_content_extractor.py`

**Interfaces:**
- Produces: module-level `_remove_chrome(soup) -> None` and `_remove_boilerplate(soup) -> None` in `content_extractor.py` (extracted from/alongside the existing `clean_html` logic; `clean_html(html) -> str` keeps its signature and existing behavior contract).

Chrome link-text patterns (extends the existing four): `privacy policy`, `terms & conditions` / `terms and conditions`, `contact us`, `about us`, `forward to a friend`, `update your details/profile/preferences`. Containment logic is unchanged from today: remove the anchor's parent `p`/`div`/`td`/`span` when its text is < 200 chars, else just the anchor.

Boilerplate block patterns (from the measured corpus census — blocks whose own text matches, when the block text is < 300 chars, are decomposed):

```python
_BOILERPLATE_PATTERNS = [
    re.compile(r"this email (was|has been) sent to", re.IGNORECASE),
    re.compile(r"registered in england and wales", re.IGNORECASE),
    re.compile(r"copyright © .* all rights reserved", re.IGNORECASE),
]
```

- [ ] **Step 1: Write the failing tests** (append to `tests/test_content_extractor.py`)

```python
def test_clean_html_removes_extended_chrome_links():
    html = """
    <div><p>Real article text that should definitely survive this pass.</p>
    <td><a href="https://e.example/privacy">Privacy Policy</a></td>
    <td><a href="https://e.example/terms">Terms &amp; Conditions</a></td>
    <p><a href="https://e.example/contact">Contact us</a></p>
    <p><a href="https://e.example/fwd">Forward to a friend</a></p></div>
    """
    cleaned = clean_html(html)
    assert "Privacy Policy" not in cleaned
    assert "Terms" not in cleaned
    assert "Contact us" not in cleaned
    assert "Forward to a friend" not in cleaned
    assert "Real article text" in cleaned


def test_clean_html_removes_boilerplate_lines():
    html = """
    <div><p>Keep this paragraph of genuine newsletter content.</p>
    <p>This email was sent to: reader@example.com</p>
    <td>This email has been sent to reader@example.com because you signed up
    for this newsletter.</td>
    <p>Registered in England and Wales. No. 236383. The Adelphi, 1-11 John
    Adam Street, London, WC2N 6HT</p>
    <p>Copyright © The Publisher Ltd 2026. All rights reserved.</p></div>
    """
    cleaned = clean_html(html)
    assert "reader@example.com" not in cleaned
    assert "Registered in England" not in cleaned
    assert "All rights reserved" not in cleaned
    assert "genuine newsletter content" in cleaned


def test_clean_html_keeps_large_blocks_mentioning_terms():
    # A long paragraph that merely links to something matching a chrome
    # pattern must not be decomposed wholesale.
    long_text = "word " * 60
    html = f'<p>{long_text}<a href="https://x.example/p">Privacy Policy</a></p>'
    cleaned = clean_html(html)
    assert "word word" in cleaned
    assert "Privacy Policy" not in cleaned  # anchor itself still removed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: the three new tests FAIL (patterns not yet present); all pre-existing tests PASS.

- [ ] **Step 3: Implement**

In `content_extractor.py`, extract the existing footer-pattern loop into `_remove_chrome(soup)` with the extended pattern list, add `_remove_boilerplate(soup)`, and call both from `clean_html` (after the pixel removal):

```python
_CHROME_PATTERNS = [
    re.compile(r"unsubscribe", re.IGNORECASE),
    re.compile(r"manage\s+(your\s+)?preferences", re.IGNORECASE),
    re.compile(r"email\s+preferences", re.IGNORECASE),
    re.compile(r"view\s+(this\s+)?(email\s+)?(online|in\s+(your\s+)?browser)", re.IGNORECASE),
    re.compile(r"privacy\s+policy", re.IGNORECASE),
    re.compile(r"terms\s*(&(amp;)?|and)\s*conditions", re.IGNORECASE),
    re.compile(r"contact\s+us", re.IGNORECASE),
    re.compile(r"about\s+us", re.IGNORECASE),
    re.compile(r"forward\s+to\s+a\s+friend", re.IGNORECASE),
    re.compile(r"update\s+your\s+(details|profile|preferences)", re.IGNORECASE),
]

_BOILERPLATE_PATTERNS = [
    re.compile(r"this email (was|has been) sent to", re.IGNORECASE),
    re.compile(r"registered in england and wales", re.IGNORECASE),
    re.compile(r"copyright © .* all rights reserved", re.IGNORECASE),
]


def _remove_chrome(soup) -> None:
    """Remove chrome links (unsubscribe/footer/nav) and their small parents."""
    for a_tag in soup.find_all("a"):
        text = a_tag.get_text(strip=True)
        if any(p.search(text) for p in _CHROME_PATTERNS):
            parent = a_tag.parent
            if parent and parent.name in ("p", "div", "td", "span"):
                if len(parent.get_text(strip=True)) < 200:
                    parent.decompose()
                    continue
            a_tag.decompose()


def _remove_boilerplate(soup) -> None:
    """Remove small blocks matching known sender-footer boilerplate."""
    for tag in soup.find_all(["p", "td", "div", "span"]):
        text = tag.get_text(" ", strip=True)
        if len(text) < 300 and any(p.search(text) for p in _BOILERPLATE_PATTERNS):
            tag.decompose()
```

`clean_html` keeps its existing structure but its footer loop is replaced by `_remove_chrome(soup)` followed by `_remove_boilerplate(soup)`. Delete the now-unused `footer_patterns` list.

Note: `_remove_boilerplate` iterates a snapshot from `find_all`; decomposing a `td` whose parent `div` is later in the list is fine — `decompose()` on an already-detached tag is guarded by checking `tag.parent is not None` at loop top if you hit `AttributeError`; add that guard only if a test forces it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: all PASS (old and new)

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/fetcher/content_extractor.py tests/test_content_extractor.py
git commit -m "feat: extend chrome removal and add sender-footer boilerplate stripping"
```

---

### Task 4: Alt-text preservation

**Files:**
- Modify: `src/newsletter_archiver/fetcher/content_extractor.py`
- Test: `tests/test_content_extractor.py`

**Interfaces:**
- Produces: `_preserve_alt_text(soup) -> None` — replaces each `img` that has a *meaningful* alt with that alt as a plain-text node. Meaningful = stripped alt has ≥ 3 words, contains no `://`, does not end in an image-file extension, and its lowercased text is not one of `{"logo", "spacer", "divider", "banner", "image", "photo", "icon"}`. All other imgs are left for markdownify's `strip=["img"]` (tracking pixels are already decomposed earlier).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_content_extractor.py`)

```python
def test_alt_text_preserved_when_meaningful():
    html = (
        '<p><img src="https://cdn.example/chart.png" '
        'alt="Chart showing quarterly revenue growth by region"></p>'
    )
    md = html_to_markdown(html)
    assert "Chart showing quarterly revenue growth by region" in md


def test_alt_text_dropped_when_boilerplate_or_short():
    html = (
        '<p><img src="https://cdn.example/a.png" alt="logo">'
        '<img src="https://cdn.example/b.png" alt="photo of thing.jpg">'
        '<img src="https://cdn.example/c.png" alt="https://cdn.example/c.png">'
        '<img src="https://cdn.example/d.png" alt="two words">'
        '<img src="https://cdn.example/e.png"></p>'
    )
    md = html_to_markdown(html)
    assert "logo" not in md
    assert "thing.jpg" not in md
    assert "cdn.example" not in md
    assert "two words" not in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: `test_alt_text_preserved_when_meaningful` FAILS (alt currently stripped with the img); the drop test may already pass — keep it as a regression guard.

- [ ] **Step 3: Implement** (in `content_extractor.py`)

```python
_ALT_BOILERPLATE = {"logo", "spacer", "divider", "banner", "image", "photo", "icon"}
_IMAGE_FILE_RE = re.compile(r"\.(png|jpe?g|gif|webp|svg)\s*$", re.IGNORECASE)


def _meaningful_alt(alt: str) -> bool:
    alt = alt.strip()
    return (
        len(alt.split()) >= 3
        and "://" not in alt
        and not _IMAGE_FILE_RE.search(alt)
        and alt.lower() not in _ALT_BOILERPLATE
    )


def _preserve_alt_text(soup) -> None:
    """Replace images that carry meaningful alt text with that text."""
    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        if _meaningful_alt(alt):
            img.replace_with(alt.strip())
```

Call `_preserve_alt_text(soup)` in `clean_html` AFTER tracking-pixel removal (so pixels never contribute alt text) and after `_remove_chrome`/`_remove_boilerplate` (so footer images die with their blocks).

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/fetcher/content_extractor.py tests/test_content_extractor.py
git commit -m "feat: preserve meaningful image alt text in markdown output"
```

---

### Task 5: Layout-table flattening with data-table guard

**Files:**
- Modify: `src/newsletter_archiver/fetcher/content_extractor.py`
- Test: `tests/test_content_extractor.py`

**Interfaces:**
- Produces: `_is_data_table(table) -> bool` and `_flatten_layout_tables(soup) -> None`.
- Data-table guard (conservative, from the spec): a table is DATA iff it contains a `<th>`, OR it has ≥ 2 own rows each with ≥ 2 own cells where every own cell has text < 80 chars and contains no block content (`p`, `div`, `table`, `img`, `ul`, `ol`, or `h1`-`h6`). Everything else is LAYOUT and gets flattened by renaming `table`/`tr`/`td` to `div` and unwrapping `thead`/`tbody`/`tfoot` — content flows as prose and markdownify never emits pipe rows for it.
- "Own" rows/cells means nearest-table-ancestor is this table (nested tables are separate). Process innermost-first (`reversed(soup.find_all("table"))`) so nested layout tables are already flattened when their parents are considered.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_content_extractor.py`)

```python
def test_layout_tables_flattened_no_pipe_rows():
    html = """
    <table role="presentation"><tbody><tr><td>
      <table><tr><td><p>The article paragraph lives deep in nested layout
      tables and must come out as clean prose.</p></td></tr></table>
    </td></tr>
    <tr><td></td><td></td><td></td></tr></tbody></table>
    """
    md = html_to_markdown(html)
    assert "| --- |" not in md
    assert "|  |" not in md
    assert "must come out as clean prose" in md


def test_data_table_with_th_survives_as_markdown_table():
    html = """
    <table><tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Revenue</td><td>$10M</td></tr>
    <tr><td>Growth</td><td>12%</td></tr></table>
    """
    md = html_to_markdown(html)
    assert "| Metric | Value |" in md
    assert "| Revenue | $10M |" in md


def test_data_table_grid_of_short_cells_survives():
    html = """
    <table><tr><td>2024</td><td>2025</td></tr>
    <tr><td>1.2</td><td>3.4</td></tr></table>
    """
    md = html_to_markdown(html)
    assert "| 2024 | 2025 |" in md


def test_table_with_block_content_is_layout():
    html = """
    <table><tr><td><p>A long-form paragraph clearly not tabular data,
    holding the actual article body.</p></td><td><p>Second column of
    prose.</p></td></tr>
    <tr><td><p>x</p></td><td><p>y</p></td></tr></table>
    """
    md = html_to_markdown(html)
    assert "| --- |" not in md
    assert "actual article body" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: layout-flattening tests FAIL (markdownify currently renders every table as pipes).

- [ ] **Step 3: Implement** (in `content_extractor.py`)

```python
_BLOCK_TAGS = ["p", "div", "table", "img", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"]


def _own(table, tag_names):
    """Descendant tags whose nearest table ancestor is this table."""
    return [t for t in table.find_all(tag_names) if t.find_parent("table") is table]


def _is_data_table(table) -> bool:
    if _own(table, ["th"]):
        return True
    rows = _own(table, ["tr"])
    if len(rows) < 2:
        return False
    for tr in rows:
        cells = [td for td in tr.find_all("td") if td.find_parent("table") is table]
        if len(cells) < 2:
            return False
        for td in cells:
            if td.find(_BLOCK_TAGS) or len(td.get_text(strip=True)) >= 80:
                return False
    return True


def _flatten_layout_tables(soup) -> None:
    """Flatten layout tables to divs; leave data tables for markdownify."""
    for table in reversed(soup.find_all("table")):
        if _is_data_table(table):
            continue
        for section in _own(table, ["thead", "tbody", "tfoot"]):
            section.unwrap()
        for cell in _own(table, ["tr", "td", "th"]):
            cell.name = "div"
        table.name = "div"
```

Call `_flatten_layout_tables(soup)` in `clean_html` as the LAST tree stage (after chrome/boilerplate/alt-text, so removed blocks don't affect the guard).

Note on `reversed(...)`: `find_all` returns document order (outer tables before the tables nested inside them), so the reversed list processes innermost tables first. After an inner layout table is renamed to `div`s, the outer table's `_own(...)` calls see through it correctly (`find_parent("table")` resolves to the outer table). An inner DATA table stays a `table`, so its cells are excluded from the outer flatten by the nearest-ancestor filter.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/fetcher/content_extractor.py tests/test_content_extractor.py
git commit -m "feat: flatten layout tables, keep data tables via conservative guard"
```

---

### Task 6: Pipeline integration — `extract_markdown()` with stats

**Files:**
- Modify: `src/newsletter_archiver/fetcher/content_extractor.py`
- Test: `tests/test_content_extractor.py`

**Interfaces:**
- Consumes: `clean_links` from `link_cleaner` (Task 2), tree stages (Tasks 3-5).
- Produces:
  ```python
  @dataclass
  class ExtractionResult:
      markdown: str
      unwrap_failures: int

  def extract_markdown(html: str) -> ExtractionResult
  ```
  `html_to_markdown(html) -> str` becomes `extract_markdown(html).markdown` (signature unchanged). Stage order inside `extract_markdown`: parse → remove script/style/noscript → remove tracking pixels → `clean_links` → `_remove_chrome` → `_remove_boilerplate` → `_preserve_alt_text` → `_flatten_layout_tables` → markdownify (ATX, `strip=["img"]`) → `strip_invisible_chars` → remove empty links (`re.sub(r"\[\s*\]\([^)]*\)", "", md)`) → collapse `\n{3,}` → strip. `clean_html(html) -> str` remains public and runs the same tree stages, returning `str(soup)` (existing tests depend on it).
- Later tasks rely on: `extract_markdown` (regenerator), `calculate_word_count`, `calculate_reading_time` (unchanged).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_content_extractor.py`)

```python
from newsletter_archiver.fetcher.content_extractor import extract_markdown


def test_extract_markdown_full_pipeline():
    html = """
    <html><body><table role="presentation"><tr><td>
    <h1>Article Title</h1>
    <p>Body text with a
    <a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fpub.example%2Fpost%3Fqs%3DTRACK">link</a>.</p>
    <p><a href="#">Unsubscribe</a></p>
    <p>This email was sent to: reader@example.com</p>
    </td></tr></table></body></html>
    """
    result = extract_markdown(html)
    assert "safelinks" not in result.markdown
    assert "https://pub.example/post" in result.markdown
    assert "Unsubscribe" not in result.markdown
    assert "reader@example.com" not in result.markdown
    assert "Article Title" in result.markdown
    assert "| --- |" not in result.markdown
    assert result.unwrap_failures == 0


def test_extract_markdown_counts_failures():
    html = '<a href="https://na01.safelinks.protection.outlook.com/?data=x">y</a>'
    assert extract_markdown(html).unwrap_failures == 1


def test_html_to_markdown_still_returns_str(sample_html):
    assert isinstance(html_to_markdown(sample_html), str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_content_extractor.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_markdown'`

- [ ] **Step 3: Implement**

Restructure `content_extractor.py`: a private `_clean_tree(soup) -> int` runs all tree stages in the order above and returns the unwrap-failure count; `clean_html` parses, calls `_clean_tree`, returns `str(soup)`; `extract_markdown` parses, calls `_clean_tree`, then does the markdown post-pass:

```python
from dataclasses import dataclass

from newsletter_archiver.fetcher.link_cleaner import clean_links


@dataclass
class ExtractionResult:
    markdown: str
    unwrap_failures: int


def _remove_tracking_pixels(soup) -> None:
    """Remove 1x1 / hidden images (extracted verbatim from the old clean_html)."""
    for img in soup.find_all("img"):
        width = img.get("width", "")
        height = img.get("height", "")
        style = img.get("style", "")
        is_tracking = (
            (width == "1" and height == "1")
            or "display:none" in style.replace(" ", "")
            or "visibility:hidden" in style.replace(" ", "")
            or (width == "0" or height == "0")
        )
        if is_tracking:
            img.decompose()


def _clean_tree(soup) -> int:
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    _remove_tracking_pixels(soup)
    failures = clean_links(soup)
    _remove_chrome(soup)
    _remove_boilerplate(soup)
    _preserve_alt_text(soup)
    _flatten_layout_tables(soup)
    return failures


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _clean_tree(soup)
    return str(soup)


def extract_markdown(html: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "html.parser")
    failures = _clean_tree(soup)
    md = markdownify(str(soup), heading_style="ATX", strip=["img"])
    md = strip_invisible_chars(md)
    md = re.sub(r"\[\s*\]\([^)]*\)", "", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return ExtractionResult(md.strip(), failures)


def html_to_markdown(html: str) -> str:
    return extract_markdown(html).markdown
```

- [ ] **Step 4: Run the FULL suite**

Run: `poetry run pytest`
Expected: all PASS — including every pre-existing test in `test_content_extractor.py`, `test_fetch_routing.py`, etc. If a pre-existing test fails, fix the pipeline (not the test) unless the test asserted the old noisy behavior.

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/fetcher/content_extractor.py tests/test_content_extractor.py
git commit -m "feat: compose retrieval-grade extraction pipeline with unwrap stats"
```

---

### Task 7: Sanitized per-publication fixtures + leak-check test

**Files:**
- Create: `tests/fixtures/stratechery.html`, `tests/fixtures/the_diff.html`, `tests/fixtures/the_economist.html`, `tests/fixtures/the_new_yorker.html`
- Test: `tests/test_fixture_extraction.py` (new)

**Interfaces:**
- Consumes: `extract_markdown` (Task 6).
- Produces: nothing for later tasks; this is the CI-safe structural regression net.

The four fixtures reproduce each publication's structural motifs, fully synthetic. CI-SAFETY IS A HARD REQUIREMENT: fixtures must contain no real email address, no real JWT (`eyJhbGciOi...`), no real tracking payloads. The leak-check test enforces it forever. Write the fixture files with exactly this content:

`tests/fixtures/stratechery.html` (simple tables, no `role`, h1/h3, access_token param, meaningful alt):

```html
<html><body>
<table><tr><td>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fstratechery.example%2Fview%3Ftoken%3DSYNTH&amp;data=05%7CSYNTH&amp;sdata=SYNTH&amp;reserved=0">View in browser</a></p>
<h1>Aggregators and Everything Else</h1>
<table><tr><td>
<p>The core argument is that demand aggregation beats supply control, a
dynamic that repeats across every market the internet touches.</p>
<h3>The Weekly Article</h3>
<p>Read the full essay:
<a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fstratechery.example%2F2026%2Fexample-essay%2F%3Faccess_token%3DSYNTHTOKENVALUE&amp;data=05%7CSYNTH&amp;reserved=0">Example Essay</a></p>
<img src="https://cdn.stratechery.example/chart.png" alt="Chart comparing aggregator margins across market segments">
<h3>Podcast</h3>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fpassport.example%2Fmember%2Fpodcast%3Furl%3Dhttps%253A%252F%252Frss.example%252Ffeed&amp;data=05%7CSYNTH&amp;reserved=0">Listen here</a></p>
</td></tr></table>
</td></tr></table>
</body></html>
```

`tests/fixtures/the_diff.html` (role=presentation tables, content/body classes, unsubscribe footer):

```html
<html><body>
<table role="presentation" class="body"><tr><td>
<div class="content">
<h2>The Strangely Reflexive Economy</h2>
<p>Longreads this week cover market microstructure, the economics of
software margins, and why reflexivity keeps showing up in places nobody
expects it to.</p>
<table role="presentation"><tr><td>
<p>Elsewhere:
<a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fthediff.example%2Fp%2Fexample-post%3Futm_source%3Demail&amp;data=05%7CSYNTH&amp;reserved=0">an essay on capital cycles</a>
worth your time.</p>
</td></tr></table>
</div>
</td></tr>
<tr><td>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fthediff.example%2Funsub%3Fm%3DSYNTH&amp;data=05%7CSYNTH&amp;reserved=0">Unsubscribe</a>
| <a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fthediff.example%2Fweb&amp;data=05%7CSYNTH&amp;reserved=0">View in browser</a></p>
</td></tr></table>
</body></html>
```

`tests/fixtures/the_economist.html` (deeply nested presentation tables, teaser digest, empty spacer cells, full footer block):

```html
<html><body>
<table role="presentation"><tbody><tr><td>
<table role="presentation"><tbody><tr><td></td><td></td><td></td></tr>
<tr><td>
<table role="presentation"><tbody><tr><td>
<h1>The world in brief</h1>
<table role="presentation"><tbody><tr><td>
<img src="https://cdn.economist.example/lead.jpg" alt="Officials gathering outside the central bank headquarters">
<h2>Schemes to juice the economy</h2>
<p>Catch up quickly on the stories that matter in economics, business and
finance, curated for the morning read.</p>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fclick.economist.example%2F%3Fqs%3DSYNTHTRACKER&amp;data=05%7CSYNTH&amp;reserved=0">Read the full story</a></p>
</td></tr></tbody></table>
<table role="presentation"><tbody><tr><td>
<h2>Second teaser</h2>
<p>A shorter item with its own link out to the site for the full text.</p>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fclick.economist.example%2F%3Fqs%3DSYNTHTRACKER2&amp;data=05%7CSYNTH&amp;reserved=0">Continue reading</a></p>
</td></tr></tbody></table>
</td></tr></tbody></table>
</td></tr>
<tr><td>
<table role="presentation"><tbody><tr><td>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fclick.economist.example%2Fcontact&amp;data=05%7CSYNTH&amp;reserved=0">Contact us</a>
<a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fclick.economist.example%2Fprivacy&amp;data=05%7CSYNTH&amp;reserved=0">Privacy Policy</a>
<a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fclick.economist.example%2Fterms&amp;data=05%7CSYNTH&amp;reserved=0">Terms &amp; Conditions</a></p>
<p>This email has been sent to reader@example.com because you signed up for
this newsletter.</p>
<p>Registered in England and Wales. No. 000000. Example House, 1 Example
Street, London</p>
<p>Copyright &#169; The Example Newspaper Limited 2026. All rights reserved.</p>
</td></tr></tbody></table>
</td></tr></tbody></table>
</td></tr></tbody></table>
</body></html>
```

`tests/fixtures/the_new_yorker.html` (heading soup h6/h4, many images, preferences footer):

```html
<html><body>
<table role="presentation"><tr><td>
<h6>The Daily Newsletter</h6>
<img src="https://cdn.tny.example/hero.jpg" alt="Illustration of a research laboratory rendered in watercolor">
<h4>The Lab Studying Whatever Comes Next</h4>
<p>Our columnist visits a research group trying to measure something that
may not be measurable at all, and finds the effort revealing.</p>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftny.example%2Farticle%2Fexample%3Futm_campaign%3DSYNTH&amp;data=05%7CSYNTH&amp;reserved=0">Read the story</a></p>
<img src="https://cdn.tny.example/spacer.gif" alt="spacer">
<h6>More from us</h6>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftny.example%2Fcrossword&amp;data=05%7CSYNTH&amp;reserved=0">Play the crossword</a></p>
</td></tr>
<tr><td>
<p><a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftny.example%2Fprefs&amp;data=05%7CSYNTH&amp;reserved=0">Manage your preferences</a>
<a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftny.example%2Fprivacy&amp;data=05%7CSYNTH&amp;reserved=0">View our Privacy Policy</a>
<a href="https://na01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftny.example%2Funsub&amp;data=05%7CSYNTH&amp;reserved=0">Unsubscribe</a></p>
<p>This email was sent to: reader@example.com</p>
</td></tr></table>
</body></html>
```

- [ ] **Step 1: Write the fixtures** (exact content above) **and the failing tests**

```python
# tests/test_fixture_extraction.py
"""Structural regression tests over sanitized per-publication fixtures.

Fixtures are fully synthetic (see leak-check test) but reproduce each
publication's real HTML motifs: SafeLink wrapping, layout-table nesting,
chrome links, boilerplate footers.
"""

from pathlib import Path

import pytest

from newsletter_archiver.fetcher.content_extractor import extract_markdown

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURES = sorted(FIXTURE_DIR.glob("*.html"))

# Content that must SURVIVE extraction, per fixture stem.
MUST_KEEP = {
    "stratechery": ["Aggregators and Everything Else", "demand aggregation",
                    "https://stratechery.example/2026/example-essay/",
                    "Chart comparing aggregator margins"],
    "the_diff": ["Strangely Reflexive", "market microstructure",
                 "https://thediff.example/p/example-post"],
    "the_economist": ["The world in brief", "Catch up quickly",
                      "Second teaser", "https://click.economist.example/"],
    "the_new_yorker": ["The Lab Studying", "may not be measurable",
                       "Illustration of a research laboratory"],
}

FORBIDDEN_IN_OUTPUT = [
    "safelinks.protection.outlook.com",
    "access_token",
    "?qs=", "&qs=",
    "reader@example.com",
    "Unsubscribe", "Privacy Policy", "| --- |",
]

FORBIDDEN_IN_FIXTURES = ["dannewman", "@outlook.com", "eyJhbGciOi"]


def test_fixtures_exist():
    assert {f.stem for f in FIXTURES} == set(MUST_KEEP)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.stem)
def test_fixtures_contain_no_real_pii(fixture):
    text = fixture.read_text(encoding="utf-8")
    for needle in FORBIDDEN_IN_FIXTURES:
        assert needle not in text, f"{fixture.name} leaks {needle!r}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.stem)
def test_extraction_keeps_content_drops_noise(fixture):
    result = extract_markdown(fixture.read_text(encoding="utf-8"))
    for needle in MUST_KEEP[fixture.stem]:
        assert needle in result.markdown, f"lost content: {needle!r}"
    for needle in FORBIDDEN_IN_OUTPUT:
        assert needle not in result.markdown, f"noise survived: {needle!r}"
    assert result.unwrap_failures == 0
```

Note `FORBIDDEN_IN_FIXTURES` uses `"@outlook.com"` (with the `@`) so the synthetic `safelinks.protection.outlook.com` hostnames don't trip it.

- [ ] **Step 2: Run tests**

Run: `poetry run pytest tests/test_fixture_extraction.py -v`
Expected: leak-check and existence tests PASS immediately; extraction tests should PASS if Tasks 1-6 are correct. Any failure here is a real pipeline bug — debug the pipeline (e.g. the nested-table guard or a chrome pattern), not the fixture, unless the fixture has a typo against the content above.

- [ ] **Step 3: Lint and commit**

```bash
poetry run ruff check .
git add tests/fixtures/ tests/test_fixture_extraction.py
git commit -m "test: sanitized per-publication fixtures with PII leak check"
```

---

### Task 8: DB metrics update — `update_newsletter_metrics()`

**Files:**
- Modify: `src/newsletter_archiver/storage/db_manager.py` (add after `get_newsletter_by_id`, ~line 272)
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `DatabaseManager.update_newsletter_metrics(markdown_path: str, word_count: int, reading_time_minutes: float) -> bool` — True if a row matched and was updated, False otherwise. UPDATE only; never inserts.

- [ ] **Step 1: Write the failing test** (append to `tests/test_storage.py`, matching its existing DatabaseManager construction pattern — it builds `DatabaseManager(db_url=f"sqlite:///{tmp_path}/...")`; copy the exact pattern used there)

```python
def test_update_newsletter_metrics(tmp_path):
    from datetime import datetime

    db = DatabaseManager(db_url=f"sqlite:///{tmp_path}/metrics.db")
    db.save_newsletter(
        message_id="m1",
        subject="S",
        sender_email="a@example.com",
        sender_name="A",
        received_date=datetime(2026, 1, 1),
        markdown_path="/arch/2026/01/a/file.md",
        html_path="/arch/2026/01/a/file.html",
        word_count=100,
        reading_time_minutes=0.5,
    )

    assert db.update_newsletter_metrics("/arch/2026/01/a/file.md", 42, 0.2) is True
    nl = db.get_all_newsletters()[0]
    assert nl.word_count == 42
    assert nl.reading_time_minutes == 0.2

    assert db.update_newsletter_metrics("/nope.md", 1, 0.1) is False
    assert db.get_newsletter_count() == 1  # no insert happened
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_storage.py -v -k metrics`
Expected: FAIL — `AttributeError: 'DatabaseManager' object has no attribute 'update_newsletter_metrics'`

- [ ] **Step 3: Implement** (in `db_manager.py`, Newsletter query operations section)

```python
def update_newsletter_metrics(
    self, markdown_path: str, word_count: int, reading_time_minutes: float
) -> bool:
    """Refresh word count metrics for the row owning markdown_path.

    Update-only: returns False (and writes nothing) when no row matches.
    """
    with self._session() as session:
        newsletter = session.execute(
            select(Newsletter).where(Newsletter.markdown_path == markdown_path)
        ).scalar_one_or_none()
        if newsletter is None:
            return False
        newsletter.word_count = word_count
        newsletter.reading_time_minutes = reading_time_minutes
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_storage.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/storage/db_manager.py tests/test_storage.py
git commit -m "feat: add update-only newsletter metrics refresh by markdown path"
```

---

### Task 9: Regenerator core — `storage/regenerator.py`

**Files:**
- Create: `src/newsletter_archiver/storage/regenerator.py`
- Test: `tests/test_regenerator.py` (new)

**Interfaces:**
- Consumes: `extract_markdown` (Task 6), `calculate_word_count`/`calculate_reading_time` (existing), `DatabaseManager.update_newsletter_metrics` (Task 8).
- Produces:
  ```python
  @dataclass
  class FileOutcome:
      html_path: Path
      status: str  # "regenerated" | "unchanged" | "skipped_no_md" | "skipped_bad_frontmatter" | "failed"
      before_chars: int = 0
      after_chars: int = 0
      unwrap_failures: int = 0
      db_row_updated: bool = False
      error: str = ""

  @dataclass
  class RegenReport:
      outcomes: list[FileOutcome]
      dry_run: bool
      # helpers: count(status) -> int, total_before -> int, total_after -> int

  def split_frontmatter(md_text: str) -> tuple[str, str] | None
  def regenerate_file(html_path: Path, db, dry_run: bool) -> FileOutcome
  def regenerate_archive(archives_dir: Path, db=None, dry_run=False, limit=None) -> RegenReport
  ```
- Semantics: frontmatter of the existing `.md` is preserved VERBATIM (the `---`-delimited block); only the body is regenerated from the paired `.html`. `status="regenerated"` means content differs from what's on disk (in dry-run nothing is written but the status still reports what would change). `.html` files are only ever read. `db=None` skips DB updates entirely (used by dry-run and tests).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_regenerator.py
"""Tests for archive regeneration from stored HTML."""

from newsletter_archiver.storage.regenerator import (
    regenerate_archive,
    split_frontmatter,
)

FRONTMATTER = '---\ntitle: "T"\nfrom: "A <a@example.com>"\ndate: 2026-01-01\n---\n'
NOISY_HTML = (
    "<html><body><table><tr><td><h1>Title</h1>"
    '<p>Body text with <a href="https://na01.safelinks.protection.outlook.com/'
    '?url=https%3A%2F%2Fpub.example%2Fpost%3Fqs%3DT">a link</a>.</p>'
    '<p><a href="#">Unsubscribe</a></p></td></tr></table></body></html>'
)


def _make_pair(root, name="2026-01-01_x"):
    d = root / "2026" / "01" / "pub"
    d.mkdir(parents=True)
    (d / f"{name}.html").write_text(NOISY_HTML, encoding="utf-8")
    (d / f"{name}.md").write_text(
        FRONTMATTER + "\nOld noisy body with safelinks garbage\n", encoding="utf-8"
    )
    return d / f"{name}.html", d / f"{name}.md"


def test_split_frontmatter_roundtrip():
    fm, body = split_frontmatter(FRONTMATTER + "\n# Body\n")
    assert fm == FRONTMATTER
    assert body == "# Body\n"
    assert split_frontmatter("no frontmatter here") is None
    assert split_frontmatter("---\nunclosed") is None


def test_regenerate_rewrites_body_preserves_frontmatter(tmp_path):
    html_path, md_path = _make_pair(tmp_path)
    report = regenerate_archive(tmp_path, db=None, dry_run=False)
    assert report.count("regenerated") == 1
    new = md_path.read_text(encoding="utf-8")
    assert new.startswith(FRONTMATTER)
    assert "https://pub.example/post" in new
    assert "safelinks" not in new
    assert "Unsubscribe" not in new
    # .html untouched
    assert html_path.read_text(encoding="utf-8") == NOISY_HTML


def test_regenerate_is_idempotent(tmp_path):
    _make_pair(tmp_path)
    regenerate_archive(tmp_path, db=None, dry_run=False)
    second = regenerate_archive(tmp_path, db=None, dry_run=False)
    assert second.count("unchanged") == 1
    assert second.count("regenerated") == 0


def test_dry_run_writes_nothing(tmp_path):
    _, md_path = _make_pair(tmp_path)
    before = md_path.read_text(encoding="utf-8")
    report = regenerate_archive(tmp_path, db=None, dry_run=True)
    assert report.count("regenerated") == 1
    assert md_path.read_text(encoding="utf-8") == before


def test_orphan_html_skipped(tmp_path):
    html_path, md_path = _make_pair(tmp_path)
    md_path.unlink()
    report = regenerate_archive(tmp_path, db=None, dry_run=False)
    assert report.count("skipped_no_md") == 1


def test_bad_frontmatter_skipped(tmp_path):
    _, md_path = _make_pair(tmp_path)
    md_path.write_text("just a body, no frontmatter", encoding="utf-8")
    report = regenerate_archive(tmp_path, db=None, dry_run=False)
    assert report.count("skipped_bad_frontmatter") == 1
    assert md_path.read_text(encoding="utf-8") == "just a body, no frontmatter"


def test_failure_is_per_file(tmp_path):
    _make_pair(tmp_path, name="2026-01-01_good")
    bad_dir = tmp_path / "2026" / "01" / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "2026-01-02_bad.html").write_bytes(b"\xff\xfe garbage bytes")
    (bad_dir / "2026-01-02_bad.md").write_text(FRONTMATTER + "\nx\n", encoding="utf-8")
    report = regenerate_archive(tmp_path, db=None, dry_run=False)
    # The good file still regenerates whether or not the bad one errors.
    assert report.count("regenerated") == 1


def test_limit(tmp_path):
    _make_pair(tmp_path, name="2026-01-01_a")
    _make_pair(tmp_path / "second", name="2026-01-01_b")
    report = regenerate_archive(tmp_path, db=None, dry_run=True, limit=1)
    assert len(report.outcomes) == 1


def test_db_metrics_updated(tmp_path):
    from datetime import datetime

    from newsletter_archiver.storage.db_manager import DatabaseManager

    html_path, md_path = _make_pair(tmp_path)
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path}/t.db")
    db.save_newsletter(
        message_id="m1", subject="T", sender_email="a@example.com",
        sender_name="A", received_date=datetime(2026, 1, 1),
        markdown_path=str(md_path), html_path=str(html_path),
        word_count=999, reading_time_minutes=9.9,
    )
    report = regenerate_archive(tmp_path, db=db, dry_run=False)
    assert report.outcomes[0].db_row_updated is True
    assert db.get_all_newsletters()[0].word_count != 999
    assert db.get_newsletter_count() == 1  # update-only, no insert
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_regenerator.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement**

```python
# src/newsletter_archiver/storage/regenerator.py
"""Regenerate markdown retrieval copies from stored HTML.

The .html files are the reading archive and are only ever read. Each .md
keeps its frontmatter verbatim; only the body is re-extracted.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from newsletter_archiver.fetcher.content_extractor import (
    calculate_reading_time,
    calculate_word_count,
    extract_markdown,
)
from newsletter_archiver.storage.db_manager import DatabaseManager

_FM_DELIM = "\n---\n"


@dataclass
class FileOutcome:
    html_path: Path
    status: str
    before_chars: int = 0
    after_chars: int = 0
    unwrap_failures: int = 0
    db_row_updated: bool = False
    error: str = ""


@dataclass
class RegenReport:
    outcomes: list[FileOutcome] = field(default_factory=list)
    dry_run: bool = False

    def count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def total_before(self) -> int:
        return sum(o.before_chars for o in self.outcomes)

    @property
    def total_after(self) -> int:
        return sum(o.after_chars for o in self.outcomes)

    @property
    def total_unwrap_failures(self) -> int:
        return sum(o.unwrap_failures for o in self.outcomes)


def split_frontmatter(md_text: str) -> Optional[tuple[str, str]]:
    """Split '---\\n...\\n---\\n' frontmatter from body.

    Returns (frontmatter_block_including_delimiters, body) or None when the
    document does not start with a well-formed frontmatter block.
    """
    if not md_text.startswith("---\n"):
        return None
    end = md_text.find(_FM_DELIM, 4)
    if end == -1:
        return None
    fm = md_text[: end + len(_FM_DELIM)]
    body = md_text[end + len(_FM_DELIM):].lstrip("\n")
    return fm, body


def regenerate_file(
    html_path: Path, db: Optional[DatabaseManager], dry_run: bool
) -> FileOutcome:
    md_path = html_path.with_suffix(".md")
    if not md_path.exists():
        return FileOutcome(html_path, "skipped_no_md")
    try:
        old_doc = md_path.read_text(encoding="utf-8")
        parts = split_frontmatter(old_doc)
        if parts is None:
            return FileOutcome(html_path, "skipped_bad_frontmatter")
        frontmatter, _ = parts

        result = extract_markdown(html_path.read_text(encoding="utf-8"))
        new_doc = frontmatter + "\n" + result.markdown + "\n"

        outcome = FileOutcome(
            html_path,
            "unchanged",
            before_chars=len(old_doc),
            after_chars=len(new_doc),
            unwrap_failures=result.unwrap_failures,
        )
        if new_doc == old_doc:
            return outcome

        outcome.status = "regenerated"
        if not dry_run:
            md_path.write_text(new_doc, encoding="utf-8")
            if db is not None:
                wc = calculate_word_count(result.markdown)
                outcome.db_row_updated = db.update_newsletter_metrics(
                    str(md_path), wc, calculate_reading_time(wc)
                )
        return outcome
    except Exception as exc:  # noqa: BLE001 - per-file isolation is the contract
        return FileOutcome(html_path, "failed", error=str(exc))


def regenerate_archive(
    archives_dir: Path,
    db: Optional[DatabaseManager] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> RegenReport:
    """Regenerate every paired .md under archives_dir from its .html."""
    html_files = sorted(archives_dir.rglob("*.html"))
    if limit is not None:
        html_files = html_files[:limit]
    report = RegenReport(dry_run=dry_run)
    for html_path in html_files:
        report.outcomes.append(regenerate_file(html_path, db, dry_run))
    return report
```

Note: `test_failure_is_per_file` writes latin-1-undecodable bytes; `read_text(encoding="utf-8")` raises, the outcome becomes `failed`, and the good file still processes. If Python's utf-8 decoder happens to accept the bytes via replacement on some platform, the test still passes because it only asserts the good file regenerated.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_regenerator.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/storage/regenerator.py tests/test_regenerator.py
git commit -m "feat: add archive regenerator preserving frontmatter, update-only DB"
```

---

### Task 10: `regenerate` CLI command + registration + README

**Files:**
- Create: `src/newsletter_archiver/cli/commands/regenerate.py`
- Modify: `src/newsletter_archiver/cli/main.py` (add import + `app.command(name="regenerate")(regenerate_app)` alongside the fetch/review/tidy registrations, lines 25-27)
- Modify: `README.md` (add the command to the commands section)
- Modify: `CLAUDE.md` (add `poetry run newsletter-archiver regenerate --dry-run` to Common Commands)
- Test: `tests/test_regenerate_cli.py` (new)

**Interfaces:**
- Consumes: `regenerate_archive` + `RegenReport` (Task 9), `get_settings().archives_dir`, `DatabaseManager` (existing).
- Produces: `newsletter-archiver regenerate [--dry-run] [--limit N]` — single function command following the `fetch` registration pattern (`app.command(name=...)(fn)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_regenerate_cli.py
"""CLI smoke test for the regenerate command."""

from typer.testing import CliRunner

from newsletter_archiver.cli.main import app

runner = CliRunner()

FRONTMATTER = '---\ntitle: "T"\nfrom: "A <a@example.com>"\ndate: 2026-01-01\n---\n'


def test_regenerate_dry_run_reports_and_writes_nothing(wired_settings):
    d = wired_settings.archives_dir / "2026" / "01" / "pub"
    d.mkdir(parents=True)
    (d / "x.html").write_text(
        "<p>Hello <a href='https://na01.safelinks.protection.outlook.com/"
        "?url=https%3A%2F%2Fp.example%2Fa'>link</a></p>",
        encoding="utf-8",
    )
    (d / "x.md").write_text(FRONTMATTER + "\nold\n", encoding="utf-8")

    result = runner.invoke(app, ["regenerate", "--dry-run"])
    assert result.exit_code == 0
    assert "dry run" in result.output.lower()
    assert (d / "x.md").read_text(encoding="utf-8") == FRONTMATTER + "\nold\n"


def test_regenerate_help_registered():
    result = runner.invoke(app, ["regenerate", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_regenerate_cli.py -v`
Expected: FAIL — `regenerate` is not a registered command (usage error, exit code 2).

- [ ] **Step 3: Implement**

```python
# src/newsletter_archiver/cli/commands/regenerate.py
"""Regenerate command - rebuild markdown retrieval copies from stored HTML."""

from typing import Optional

import typer
from rich import print as rprint

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.storage.regenerator import regenerate_archive


def app(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would change without writing anything"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Process only the first N files (sorted order)"
    ),
):
    """Rebuild every .md retrieval copy from its stored .html (never refetches)."""
    settings = get_settings()

    db = None
    if not dry_run:
        from newsletter_archiver.storage.db_manager import DatabaseManager

        db = DatabaseManager()

    mode = "Dry run" if dry_run else "Regenerating"
    rprint(f"[bold]{mode}: scanning {settings.archives_dir}...[/bold]")

    report = regenerate_archive(
        settings.archives_dir, db=db, dry_run=dry_run, limit=limit
    )

    changed = report.count("regenerated")
    rprint(
        f"\n[bold]Results:[/bold] {changed} changed, "
        f"{report.count('unchanged')} unchanged, "
        f"{report.count('skipped_no_md')} without .md, "
        f"{report.count('skipped_bad_frontmatter')} bad frontmatter, "
        f"{report.count('failed')} failed"
    )
    if report.total_before:
        pct = 100 * (report.total_before - report.total_after) / report.total_before
        rprint(
            f"Size: {report.total_before:,} -> {report.total_after:,} chars "
            f"({pct:.1f}% smaller)"
        )
    if report.total_unwrap_failures:
        rprint(f"[yellow]SafeLink unwrap failures: {report.total_unwrap_failures}[/yellow]")

    top = sorted(
        (o for o in report.outcomes if o.status == "regenerated"),
        key=lambda o: o.after_chars - o.before_chars,
    )[:10]
    if top and dry_run:
        rprint("\n[bold]Top reductions:[/bold]")
        for o in top:
            rprint(f"  {o.before_chars:>9,} -> {o.after_chars:>9,}  {o.html_path.name}")

    for o in report.outcomes:
        if o.status == "failed":
            rprint(f"[red]FAILED[/red] {o.html_path}: {o.error}")

    if dry_run:
        rprint("\n[yellow]Dry run: no files written.[/yellow]")
    if report.count("failed"):
        raise typer.Exit(1)
```

In `main.py` add `from newsletter_archiver.cli.commands.regenerate import app as regenerate_app` (keep imports alphabetical) and register after tidy: `app.command(name="regenerate")(regenerate_app)`.

README: add to the commands/usage section:

```markdown
# Rebuild all markdown retrieval copies from stored HTML (no refetch)
poetry run newsletter-archiver regenerate --dry-run   # stats only
poetry run newsletter-archiver regenerate             # write changes
```

CLAUDE.md Common Commands gets the same two lines.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_regenerate_cli.py -v` then the full suite `poetry run pytest`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
poetry run ruff check .
git add src/newsletter_archiver/cli/commands/regenerate.py src/newsletter_archiver/cli/main.py README.md CLAUDE.md tests/test_regenerate_cli.py
git commit -m "feat: add regenerate CLI command with dry-run stats report"
```

---

### Task 11: Local-only integration test over the real archive

**Files:**
- Create: `tests/test_real_archive_integration.py`

**Interfaces:**
- Consumes: `extract_markdown` (Task 6). Runs ONLY on this machine (auto-skips in CI where the Proton Drive path doesn't exist). Reads a bounded set of real files (Proton I/O is slow — never glob the whole archive here).

- [ ] **Step 1: Write the test**

```python
# tests/test_real_archive_integration.py
"""Integration checks against the real archive. Auto-skipped when absent (CI)."""

from pathlib import Path

import pytest

from newsletter_archiver.fetcher.content_extractor import extract_markdown

REAL_ARCHIVE = Path(
    "/mnt/c/Users/danne/Proton Drive/noomonics/My files/Projects/"
    "newsletter-archive/archives"
)

pytestmark = pytest.mark.skipif(
    not REAL_ARCHIVE.exists(), reason="real archive not present (CI-safe skip)"
)

PUBLICATIONS = ["stratechery", "the-diff", "the-economist", "the-new-yorker"]


def _one_sample(pub: str) -> Path:
    files = sorted((REAL_ARCHIVE / "2026" / "02" / pub).glob("*.html"))
    assert files, f"no stored html for {pub}"
    return files[0]


@pytest.mark.parametrize("pub", PUBLICATIONS)
def test_real_extraction_invariants(pub):
    html = _one_sample(pub).read_text(encoding="utf-8", errors="replace")
    result = extract_markdown(html)
    md = result.markdown

    assert "safelinks.protection.outlook.com" not in md
    assert "access_token=" not in md
    assert "?qs=" not in md and "&qs=" not in md
    assert "| --- | --- |" not in md
    assert result.unwrap_failures == 0
    assert len(md) > 200, "over-stripped: nearly nothing survived"
    assert len(md) < len(html), "output should shrink"
```

- [ ] **Step 2: Run it locally**

Run: `poetry run pytest tests/test_real_archive_integration.py -v`
Expected: 4 PASS on this machine. If any invariant fails, that's a real pipeline gap against real data — fix the pipeline stage responsible, re-run the unit suite, then this again.

- [ ] **Step 3: Verify CI-safety of the skip**

Run: `poetry run pytest tests/test_real_archive_integration.py -v --co -q` and confirm collection works; the skipif guard means CI (no `/mnt/c/...`) skips all 4. Also run the FULL suite once more: `poetry run pytest`.
Expected: everything green.

- [ ] **Step 4: Lint and commit**

```bash
poetry run ruff check .
git add tests/test_real_archive_integration.py
git commit -m "test: local-only integration invariants over the real archive"
```

---

## After the plan: acceptance run (user-visible, not a task for subagents)

Manual verification per the spec's acceptance criteria, run in the main session after Task 11:

1. `poetry run newsletter-archiver regenerate --dry-run` over all 789 → expect ~50% total shrink, review top offenders and any unwrap failures/skips.
2. Spot-check 2-3 regenerated bodies (dry-run doesn't write; do this after step 3).
3. `poetry run newsletter-archiver regenerate` (the real run — Proton Drive sync means this is effectively publishing; get user go-ahead first).
4. `poetry run newsletter-archiver regenerate` again → expect 0 changed (idempotency).
5. Confirm `.html` untouched (mtimes/content) and DB row count unchanged.
6. Hand back to local-rag per the 2026-08-09 handoff (incremental reindex + re-measurements) — separate workstream.
