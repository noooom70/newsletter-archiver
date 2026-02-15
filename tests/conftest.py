"""Shared test fixtures."""

import pytest
from pathlib import Path
import tempfile

from newsletter_archiver.core.config import Settings


@pytest.fixture
def tmp_archive(tmp_path):
    """Provide a temporary archive directory."""
    return tmp_path / "archive"


@pytest.fixture
def settings(tmp_archive):
    """Provide test settings with temp directories."""
    return Settings(
        azure_client_id="test-client-id",
        azure_client_secret="test-client-secret",
        archive_dir=tmp_archive,
        local_dir=tmp_archive / "local",
    )


@pytest.fixture
def sample_html():
    """Sample newsletter HTML content."""
    return """
    <html>
    <head><style>body { font-family: Arial; }</style></head>
    <body>
        <h1>Weekly Tech Digest</h1>
        <p>Here are this week's top stories:</p>
        <h2>Rust Memory Safety</h2>
        <p>A deep dive into how Rust prevents memory bugs at compile time.</p>
        <img src="https://tracker.example.com/pixel.gif" width="1" height="1">
        <script>console.log('tracking')</script>
        <p><a href="#">Unsubscribe</a> | <a href="#">Manage your subscription</a></p>
    </body>
    </html>
    """
