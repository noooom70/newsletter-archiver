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
