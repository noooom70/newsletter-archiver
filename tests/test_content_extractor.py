"""Tests for HTML cleanup, Markdown conversion, and newsletter detection."""

from newsletter_archiver.fetcher.content_extractor import (
    build_markdown_document,
    calculate_reading_time,
    calculate_word_count,
    clean_html,
    html_to_markdown,
)
from newsletter_archiver.fetcher.email_parser import _is_transactional_subject


def test_clean_html_removes_scripts(sample_html):
    cleaned = clean_html(sample_html)
    assert "<script>" not in cleaned
    assert "tracking" not in cleaned


def test_clean_html_removes_styles(sample_html):
    cleaned = clean_html(sample_html)
    assert "<style>" not in cleaned


def test_clean_html_removes_tracking_pixels(sample_html):
    cleaned = clean_html(sample_html)
    assert 'width="1"' not in cleaned
    assert "pixel.gif" not in cleaned


def test_clean_html_removes_unsubscribe_links(sample_html):
    cleaned = clean_html(sample_html)
    assert "Unsubscribe" not in cleaned


def test_html_to_markdown_preserves_content(sample_html):
    md = html_to_markdown(sample_html)
    assert "Weekly Tech Digest" in md
    assert "Rust Memory Safety" in md
    assert "memory bugs" in md


def test_html_to_markdown_removes_noise(sample_html):
    md = html_to_markdown(sample_html)
    assert "pixel.gif" not in md
    assert "<script>" not in md


def test_build_markdown_document():
    doc = build_markdown_document(
        subject="Test Newsletter",
        sender_name="Test Author",
        sender_email="test@example.com",
        received_date="2025-01-15T10:00:00",
        markdown_body="# Hello\n\nThis is a test.",
    )
    assert "title: \"Test Newsletter\"" in doc
    assert 'from: "Test Author <test@example.com>"' in doc
    assert "# Hello" in doc


def test_calculate_word_count():
    assert calculate_word_count("hello world foo bar") == 4
    assert calculate_word_count("") == 0


def test_calculate_reading_time():
    assert calculate_reading_time(200) == 1.0
    assert calculate_reading_time(500) == 2.5
    assert calculate_reading_time(0) == 0.0


def test_transactional_subject_detection():
    # Should be detected as transactional
    assert _is_transactional_subject("Your receipt from Stratechery")
    assert _is_transactional_subject("Your Order Confirmation #12345")
    assert _is_transactional_subject("Confirm your email address")
    assert _is_transactional_subject("Password Reset Request")
    assert _is_transactional_subject("Your invoice for February")
    assert _is_transactional_subject("Welcome to Our Service")
    assert _is_transactional_subject("Your Stratechery subscription will renew soon.")

    # Should NOT be detected as transactional
    assert not _is_transactional_subject("Aggregators and AI (This Week in Stratechery)")
    assert not _is_transactional_subject("The Disappearance of Nancy Guthrie")
    assert not _is_transactional_subject("Longreads + Open Thread")
    assert not _is_transactional_subject("The World in Brief: Rubio love-bombs Europe")


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
