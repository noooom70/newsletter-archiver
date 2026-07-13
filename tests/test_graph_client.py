"""Tests for Graph API client retry and resilience logic."""

import json
from unittest.mock import MagicMock, patch

import pytest

from newsletter_archiver.core.exceptions import FetchError
from newsletter_archiver.fetcher.graph_client import GraphClient


@pytest.fixture
def client():
    """Create a GraphClient with mocked auth."""
    with patch.object(GraphClient, "_get_token", return_value="fake-token"):
        c = GraphClient()
        c._token = "fake-token"
        yield c


def _mock_response(status_code, json_data=None, headers=None):
    """Create a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.text = json.dumps(json_data or {})
    return resp


class TestGraphGetRetries:
    def test_retries_after_429_and_succeeds(self, client):
        """429 with Retry-After header should retry and succeed."""
        resp_429 = _mock_response(429, {"error": "throttled"}, {"Retry-After": "1"})
        resp_200 = _mock_response(200, {"value": [{"id": "1"}]})

        with patch("newsletter_archiver.fetcher.graph_client.requests.get",
                    side_effect=[resp_429, resp_200]), \
             patch("newsletter_archiver.fetcher.graph_client.time.sleep") as mock_sleep:
            result = client._graph_get("/me/messages")
            assert result == {"value": [{"id": "1"}]}
            mock_sleep.assert_called_once_with(1.0)

    def test_retries_after_503_and_succeeds(self, client):
        """503 should retry with backoff."""
        resp_503 = _mock_response(503, {"error": "busy"})
        resp_200 = _mock_response(200, {"value": []})

        with patch("newsletter_archiver.fetcher.graph_client.requests.get",
                    side_effect=[resp_503, resp_200]), \
             patch("newsletter_archiver.fetcher.graph_client.time.sleep") as mock_sleep:
            result = client._graph_get("/me/messages")
            assert result == {"value": []}
            mock_sleep.assert_called_once()

    def test_raises_after_max_retries(self, client):
        """Should raise FetchError after exhausting retries."""
        resp_429 = _mock_response(429, {"error": "throttled"}, {"Retry-After": "1"})

        with patch("newsletter_archiver.fetcher.graph_client.requests.get",
                    return_value=resp_429), \
             patch("newsletter_archiver.fetcher.graph_client.time.sleep"):
            with pytest.raises(FetchError, match="Graph API error 429"):
                client._graph_get("/me/messages")

    def test_401_clears_token_and_retries(self, client):
        """401 should clear cached token, re-auth, and retry once."""
        resp_401 = _mock_response(401, {"error": "unauthorized"})
        resp_200 = _mock_response(200, {"value": []})

        with patch("newsletter_archiver.fetcher.graph_client.requests.get",
                    side_effect=[resp_401, resp_200]), \
             patch.object(client, "_get_token", return_value="new-token") as mock_token:
            result = client._graph_get("/me/messages")
            assert result == {"value": []}
            # Token should have been cleared and re-fetched
            assert mock_token.call_count >= 2


class TestPagination:
    def test_follows_nextlink(self, client):
        """Should follow @odata.nextLink for all pages."""
        page1 = {"value": [{"id": "1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1"}
        page2 = {"value": [{"id": "2"}]}

        with patch.object(client, "_graph_get", side_effect=[page1, page2]) as mock_graph:
            result = client.fetch_emails(days_back=7)
            assert len(result) == 2
            assert result[0]["id"] == "1"
            assert result[1]["id"] == "2"
            # Second call should use the full nextLink URL
            assert mock_graph.call_args_list[1][0][0] == "https://graph.microsoft.com/v1.0/me/messages?$skip=1"

    def test_pagination_routes_through_graph_get(self, client):
        """Pagination uses _graph_get (which has retry logic) for subsequent pages."""
        page1 = {"value": [{"id": "1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1"}
        page2 = {"value": [{"id": "2"}]}

        with patch.object(client, "_graph_get", side_effect=[page1, page2]) as mock_graph:
            result = client.fetch_emails(days_back=7)
            assert len(result) == 2
            # Both calls should go through _graph_get (not raw requests.get)
            assert mock_graph.call_count == 2

    def test_sender_filter_quotes_escaped(self, client):
        """Single quotes in the sender filter must be escaped per OData rules."""
        page = {"value": []}

        with patch.object(client, "_graph_get", return_value=page) as mock_graph:
            client.fetch_emails(days_back=7, sender_filter="o'brien@example.com")
            params = mock_graph.call_args[1]["params"]
            assert "o''brien@example.com" in params["$filter"]

    def test_pagination_logs_warning_on_failure(self, client):
        """Unrecoverable error during pagination should log and return partial results."""
        page1 = {"value": [{"id": "1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1"}

        with patch.object(client, "_graph_get", side_effect=[page1, FetchError("Graph API error 500: internal")]):
            with patch("newsletter_archiver.fetcher.graph_client.logger") as mock_logger:
                result = client.fetch_emails(days_back=7)
                assert len(result) == 1
                assert result[0]["id"] == "1"
                mock_logger.warning.assert_called_once()
