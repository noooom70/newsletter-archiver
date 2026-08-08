"""The vector/RAG layer degrades gracefully when the 'rag' extra is absent."""

from typer.testing import CliRunner

from newsletter_archiver.search import optional_deps

runner = CliRunner()


def _disable_rag(monkeypatch):
    monkeypatch.setattr(optional_deps, "rag_available", lambda: False)


def test_semantic_search_exits_with_hint(monkeypatch, wired_settings):
    from newsletter_archiver.cli.commands.search import app

    _disable_rag(monkeypatch)
    result = runner.invoke(app, ["semantic", "anything"])
    assert result.exit_code == 1
    assert "rag" in result.output


def test_ask_exits_with_hint(monkeypatch, wired_settings):
    from newsletter_archiver.cli.commands.search import app

    _disable_rag(monkeypatch)
    result = runner.invoke(app, ["ask", "anything"])
    assert result.exit_code == 1
    assert "rag" in result.output


def test_index_build_vector_only_exits_with_hint(monkeypatch, wired_settings):
    from newsletter_archiver.cli.commands.index import app

    _disable_rag(monkeypatch)
    result = runner.invoke(app, ["build", "--vector-only"])
    assert result.exit_code == 1
    assert "rag" in result.output


def test_index_build_falls_back_to_fts(monkeypatch, wired_settings):
    from newsletter_archiver.cli.commands.index import app

    _disable_rag(monkeypatch)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0
    assert "FTS" in result.output


def test_indexer_skips_vector_when_rag_missing(monkeypatch, wired_settings, tmp_path):
    _disable_rag(monkeypatch)

    from newsletter_archiver.search.indexer import SearchIndexer

    md = tmp_path / "note.md"
    md.write_text("# Hello\n\nSome newsletter content.")

    indexer = SearchIndexer()
    assert indexer.vector_enabled is False

    indexer.index_newsletter(
        newsletter_id=1, subject="Test", sender_name="Sender",
        markdown_path=str(md), fts=True, vector=True,
    )
    # The vector store must never have been touched, let alone loaded
    assert indexer._vector is None

    _, vector_count = indexer.index_all()
    assert vector_count == 0


def test_keyword_search_works_without_rag(monkeypatch, wired_settings):
    from newsletter_archiver.cli.commands.search import app

    _disable_rag(monkeypatch)
    result = runner.invoke(app, ["keyword", "anything"])
    assert result.exit_code == 0
