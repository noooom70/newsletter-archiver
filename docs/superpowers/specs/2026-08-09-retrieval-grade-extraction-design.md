# Retrieval-Grade Content Extraction + Archive Regeneration — Design

**Date:** 2026-08-09
**Status:** Approved (design review with user, 2026-08-09)

## Problem

The archiver's `.md` files are the retrieval copy consumed by search indexes
(local-rag externally; the optional `rag` extra internally). Measurement on the
real 789-file archive (2026-08-09) showed the markdown is ~57% tracking-URL
noise by characters: 22,473 Outlook SafeLinks wrappers (14.24MB of a 25.1MB
corpus), tracking query params (including Stratechery subscriber
`access_token` JWTs — a credential-hygiene issue — and `email=` PII), email
chrome (unsubscribe/footer blocks), and layout-table scaffolding (520KB+ of
pipe-separator rows). This noise inflates embedding memory (~3.5 tokens per
whitespace-word vs ~1.3 for prose) and pollutes retrieval.

## Governing decisions (settled with user, 2026-08-09)

- **Markdown = retrieval copy, HTML = reading copy.** The `.html` files
  preserve the newsletter as published and are **never modified**. Aggressive
  cleanup of `.md` is correct by design.
- **Keep the article and its embedded links** (unwrapped, tracking-stripped);
  drop chrome (unsubscribe, view-in-browser, about/nav, sender footers).
- For digest newsletters (e.g. The Economist), all teaser text and links are
  content; only footer chrome is dropped.
- **Meaningful image alt text is preserved as plain text**; all images are
  otherwise stripped as today.
- Regeneration sources from stored `.html` only — never refetch (old mail may
  be gone from the mailbox).
- Approach: **generic heuristic pipeline** (publication-agnostic). No
  per-publication config schema, no readability-style library. Per-publication
  hints in `publications.yaml` remain a future escape hatch only.

## Evidence base (measured on the real corpus; see handoff of 2026-08-09)

- SafeLinks: 22,473 wrapped URLs in 787/789 files; all recoverable from the
  percent-encoded `url=` param, zero failures. Two files arrived unwrapped —
  the wrapper cannot be assumed present.
- Query-param census of decoded destinations: everything is tracking except
  `v=` (YouTube video identity, 55 links / 770 chars). Keeplist = `{v}`.
- Structural scan (one sample per publication): zero `<th>` anywhere — every
  sampled table is layout. `role=presentation` is common but absent in
  Stratechery, so it cannot be the only signal. Chrome links are few and
  identifiable by text.

## Component 1: extraction pipeline (`fetcher/content_extractor.py`)

All cleaning happens on the parsed BeautifulSoup tree in one pass before
markdownify. Public API unchanged: `html_to_markdown(html) -> str`,
`build_markdown_document(...)` untouched — `fetch` and `regenerate` share the
identical path.

Pipeline order:

1. **Unwrap SafeLinks.** For every `a[href]` on
   `*.safelinks.protection.outlook.com`: extract the `url=` query param,
   unquote, validate the result starts with `http://` or `https://`, replace
   the href. On missing/invalid param: keep the original href and count it for
   the run report. Nested `url=` redirects unwrap one level only (the outer
   SafeLink); inner redirects are publisher links and stay.
2. **Strip tracking params on every href** (not only formerly-wrapped ones):
   `parse_qsl` → keep only `KEEP_PARAMS = {"v"}` → rebuild with
   `urlencode`/`urlunsplit`. Removes `qs=` click-trackers, `access_token`
   JWTs, `email=` PII, `unsub`, `m`, etc.
3. **Existing cleanup retained:** `script`/`style`/`noscript` removal,
   tracking-pixel image removal.
4. **Chrome removal.** Extend the current link-text pattern list (unsubscribe,
   view-in-browser, manage/email preferences) with: privacy policy, terms,
   contact us, about us, forward-to-a-friend, update-profile. Same
   containment logic as today (remove the small parent block, <200 chars).
   Additionally remove blocks matching measured exact-line boilerplate:
   "This email was sent to \<address\>" and the Economist postal footer.
5. **Alt-text preservation.** An `img` whose `alt` is meaningful — ≥3 words,
   not filename/URL-shaped, not boilerplate ("logo", "spacer", "divider",
   "banner", "image") — is replaced by its alt as plain text. All other
   images stripped (markdownify `strip=["img"]` as today).
6. **Layout-table unwrapping.** Tables are unwrapped (tags removed, children
   flow as prose) unless the conservative data-table guard fires: the table
   contains a `<th>`, OR is a ≥2×2 grid of short plain cells (<80 chars)
   with no nested block content (p/div/table/img). Guarded tables convert to
   real markdown tables. In the sampled corpus zero tables trip the guard.
7. **Markdown post-pass.** markdownify (ATX headings), invisible-char
   stripping, re-encode `(` → `%28`, `)` → `%29`, and space → `%20` inside
   URLs so substituted links can't break markdown syntax (parens as a pair
   for visual consistency), whitespace collapse.

## Component 2: `regenerate` command (`cli/commands/regenerate.py`)

`newsletter-archiver regenerate [--dry-run] [--limit N]`

`--limit N` processes only the first N discovered files (deterministic sorted
order) — for incremental validation before a full run.

- Walk the archive dir for `*.html`; pair each with its `.md` via the
  `with_suffix` convention in `storage/file_manager.py`.
- **Frontmatter preserved verbatim**: read the existing `.md`, keep its
  `---`-delimited frontmatter block as-is, regenerate only the body from the
  HTML. Zero metadata drift for downstream date filtering. An `.html` with no
  paired `.md` is skipped and reported — never guess metadata.
- **DB: updates only, never inserts.** Match the row by `markdown_path`;
  refresh `word_count` and `reading_time_minutes`. No new rows — the
  sender-scoped `internet_message_id` dedup (2efc258) is untouched. A file
  with no DB row is reported, not created.
- `--dry-run`: full stats report (per-file before/after chars, corpus totals,
  top offenders, unwrap-failure/skip counts) with zero writes. This is the
  go/no-go gate before touching Proton Drive.
- **Write only on change**: compare new content to old; skip identical.
  Idempotent — a second run reports zero writes. `.html` files are never
  opened for writing anywhere in the code path.

## Error handling

- Regeneration is per-file isolated: one failure logs and continues.
  End-of-run summary (regenerated / unchanged / skipped / failed); non-zero
  exit if any failed.
- Unwrap failures keep the original href and increment a counter — the file
  still regenerates.
- Proton Drive quirks (slow I/O, files vanishing mid-scan) are per-file
  failures, not run-killers.

## Testing

Two tiers — **CI-safety is a hard requirement** (repo is public; real HTML
contains the user's email address and live subscriber JWTs; raw fixtures must
never be committed):

1. **CI-safe unit fixtures**: small HTML fixtures reproducing each
   publication's real structure (table nesting, chrome blocks, SafeLink
   wrappers) with all addresses/tokens replaced by synthetic values. Unit
   tests per pipeline stage: unwrap (incl. missing-`url=` and nested-redirect
   cases), param stripping (keeplist honored), chrome removal, alt-text
   keep/drop, data-table guard in both directions, frontmatter preservation,
   regenerate idempotency and skip paths (tmp dirs).
2. **Local integration test**, auto-skipped when the Proton archive path is
   absent (so CI never sees it): full pipeline over a handful of real stored
   files, asserting invariants — no `safelinks.` substring in output, no
   `access_token=`, no `email=`, output shrank, frontmatter intact.

## Acceptance criteria

- Dry-run over all 789 files shows the expected ~50% corpus shrink.
- Spot-checked regenerated files read as clean article + embedded links.
- A second `regenerate` run reports zero writes (idempotency).
- `.html` files bit-identical before/after; DB row count unchanged.

## Out of scope / follow-ups

- Hand-back to local-rag after regeneration (incremental reindex, restore the
  README newsletter-share figure, re-measure the newsletter-cap premise and
  hybrid-vs-dense on clean data) — tracked in the 2026-08-09 handoff.
- Rebuild of the archiver's own optional `rag` index on machines that have it
  (not this one).
- Per-publication extraction hints in `publications.yaml` — only if a
  publication proves misbehaved.
