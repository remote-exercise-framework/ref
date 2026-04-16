"""
Unit Tests for REFWebClient

These tests verify the web client helper functions work correctly.
All tests in this file can run without a running REF instance.
"""

import pytest

from helpers.web_client import REFWebClient


@pytest.mark.offline
class TestREFWebClientOffline:
    """Test REFWebClient offline functionality (no REF required)."""

    def test_client_initialization(self):
        """Test that client initializes correctly."""
        client = REFWebClient("http://localhost:8000")
        assert client.base_url == "http://localhost:8000"
        assert client.client is not None
        assert not client.is_logged_in()
        client.close()

    def test_client_strips_trailing_slash(self):
        """Test that client strips trailing slash from base URL."""
        client = REFWebClient("http://localhost:8000/")
        assert client.base_url == "http://localhost:8000"
        client.close()

    def test_client_with_custom_timeout(self):
        """Test that client accepts custom timeout."""
        client = REFWebClient("http://localhost:8000", timeout=60.0)
        assert client.timeout == 60.0
        client.close()

    def test_is_logged_in_initially_false(self):
        """Test that client is not logged in initially."""
        client = REFWebClient("http://localhost:8000")
        assert client.is_logged_in() is False
        client.close()

    def test_close_is_safe(self):
        """Test that close can be called safely."""
        client = REFWebClient("http://localhost:8000")
        client.close()
        # Should not raise exception
        client.close()
