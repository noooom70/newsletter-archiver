"""Custom exceptions for newsletter archiver."""


class NewsletterArchiverError(Exception):
    """Base exception for all newsletter archiver errors."""


class ConfigError(NewsletterArchiverError):
    """Configuration is missing or invalid."""


class AuthError(NewsletterArchiverError):
    """Authentication with Microsoft Graph failed."""


class FetchError(NewsletterArchiverError):
    """Failed to fetch emails from Outlook."""


class ParseError(NewsletterArchiverError):
    """Failed to parse email content."""


class StorageError(NewsletterArchiverError):
    """Failed to store newsletter to disk or database."""
