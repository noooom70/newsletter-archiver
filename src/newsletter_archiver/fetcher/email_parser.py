"""Parse email messages and detect newsletters."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    sender_email: str
    sender_name: str
    received_date: datetime
    html_body: str
    text_body: str
    is_newsletter: bool
    headers: dict


def parse_message(message) -> ParsedEmail:
    """Parse an O365 Message object into a ParsedEmail.

    Args:
        message: An O365 Message object.

    Returns:
        ParsedEmail with extracted fields.
    """
    sender = message.sender
    sender_email = sender.address if sender else ""
    sender_name = sender.name if sender else ""

    html_body = message.body or ""
    # O365 returns HTML body by default; get plain text too
    text_body = ""

    # Check for newsletter indicators
    is_newsletter = _detect_newsletter(message, html_body)

    return ParsedEmail(
        message_id=message.object_id or "",
        subject=message.subject or "(No Subject)",
        sender_email=sender_email,
        sender_name=sender_name,
        received_date=message.received or datetime.utcnow(),
        html_body=html_body,
        text_body=text_body,
        is_newsletter=is_newsletter,
        headers={},
    )


def _detect_newsletter(message, html_body: str) -> bool:
    """Heuristic to determine if a message is a newsletter.

    Checks for:
    - List-Unsubscribe header (most reliable)
    - Common newsletter sender patterns
    - Unsubscribe links in body
    """
    # Check List-Unsubscribe header via message properties
    # O365 doesn't expose raw headers easily, so we check the body
    # and known patterns

    # Check body for unsubscribe indicators
    body_lower = html_body.lower()
    unsubscribe_indicators = [
        "list-unsubscribe",
        "unsubscribe",
        "email preferences",
        "manage your subscription",
        "opt out",
        "update your preferences",
    ]

    indicator_count = sum(
        1 for ind in unsubscribe_indicators if ind in body_lower
    )

    # Common newsletter platform domains
    newsletter_domains = [
        "substack.com",
        "beehiiv.com",
        "convertkit.com",
        "mailchimp.com",
        "buttondown.email",
        "revue.email",
        "ghost.io",
        "sendfox.com",
    ]

    sender_email = ""
    if message.sender:
        sender_email = message.sender.address.lower()

    from_newsletter_platform = any(
        domain in sender_email for domain in newsletter_domains
    )

    # Score-based: 2+ indicators or from known platform
    return indicator_count >= 2 or from_newsletter_platform
