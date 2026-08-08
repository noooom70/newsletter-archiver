"""Mark archived newsletters read and move them out of the inbox."""

import logging

from newsletter_archiver.core.exceptions import FetchError
from newsletter_archiver.fetcher.graph_client import GraphClient
from newsletter_archiver.storage.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


def tidy_newsletter(
    graph: GraphClient,
    db: DatabaseManager,
    newsletter_id: int,
    message_id: str,
    internet_message_id: str = "",
) -> bool:
    """Mark an archived newsletter's email read and move it to Archive.

    Best-effort: a Graph failure is logged and reported as False, never
    raised. A 404 (message deleted or already moved) counts as done.
    Returns True when the newsletter is now tidy.
    """
    try:
        graph.mark_read(message_id)
        new_message_id = graph.archive_message(message_id)
    except FetchError as e:
        if e.status_code == 404:
            db.mark_newsletter_tidied(
                newsletter_id, internet_message_id=internet_message_id,
            )
            return True
        logger.warning(
            "Failed to tidy mailbox message for newsletter %s", newsletter_id,
            exc_info=True,
        )
        return False

    db.mark_newsletter_tidied(
        newsletter_id,
        new_message_id=new_message_id,
        internet_message_id=internet_message_id,
    )
    return True
