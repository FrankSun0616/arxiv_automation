import io
import unittest
import urllib.error
from unittest import mock

import arxiv_digest


ATOM_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <updated>2026-05-18T00:00:00Z</updated>
    <published>2026-05-18T00:00:00Z</published>
    <title>Test paper</title>
    <summary>Test summary</summary>
    <author><name>ATLAS Collaboration</name></author>
    <category term="hep-ex" />
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FetchFeedRetryTests(unittest.TestCase):
    def test_retries_http_429_and_then_succeeds(self):
        attempts = {"count": 0}

        def fake_urlopen(request, timeout):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "Too Many Requests",
                    {"Retry-After": "0"},
                    io.BytesIO(b""),
                )
            return FakeResponse(ATOM_FEED)

        with (
            mock.patch("arxiv_digest.urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("arxiv_digest.time.sleep") as sleep_mock,
        ):
            feed = arxiv_digest.fetch_feed(
                "(cat:hep-ex)",
                5,
                timeout_seconds=1,
                retry_attempts=2,
                retry_delay_base_seconds=0,
            )

        self.assertEqual(feed.tag, f"{arxiv_digest.ATOM}feed")
        self.assertEqual(attempts["count"], 2)
        sleep_mock.assert_called_once_with(0)

    def test_does_not_retry_non_retryable_http_error(self):
        def fake_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(b""),
            )

        with (
            mock.patch("arxiv_digest.urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("arxiv_digest.time.sleep") as sleep_mock,
        ):
            with self.assertRaises(urllib.error.HTTPError):
                arxiv_digest.fetch_feed(
                    "(cat:hep-ex)",
                    5,
                    timeout_seconds=1,
                    retry_attempts=3,
                    retry_delay_base_seconds=0,
                )

        sleep_mock.assert_not_called()

    def test_retries_timeout_and_then_succeeds(self):
        attempts = {"count": 0}

        def fake_urlopen(request, timeout):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TimeoutError("The read operation timed out")
            return FakeResponse(ATOM_FEED)

        with (
            mock.patch("arxiv_digest.urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("arxiv_digest.time.sleep") as sleep_mock,
        ):
            feed = arxiv_digest.fetch_feed(
                "(cat:hep-ex)",
                5,
                timeout_seconds=1,
                retry_attempts=2,
                retry_delay_base_seconds=0,
            )

        self.assertEqual(feed.tag, f"{arxiv_digest.ATOM}feed")
        self.assertEqual(attempts["count"], 2)
        sleep_mock.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
