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
