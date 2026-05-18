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

RSS_FEED = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <item>
      <title>RSS test paper</title>
      <link>https://arxiv.org/abs/2605.12345</link>
      <description>arXiv:2605.12345v1 Announce Type: new Abstract: RSS abstract text.</description>
      <category>hep-ex</category>
      <category>physics.data-an</category>
      <pubDate>Mon, 18 May 2026 00:00:00 +0000</pubDate>
      <dc:creator>ATLAS Collaboration</dc:creator>
    </item>
  </channel>
</rss>
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

    def test_fetch_papers_from_rss_parses_and_deduplicates(self):
        def fake_urlopen(request, timeout):
            return FakeResponse(RSS_FEED)

        with mock.patch("arxiv_digest.urllib.request.urlopen", side_effect=fake_urlopen):
            papers = arxiv_digest.fetch_papers_from_rss(
                ["hep-ex", "physics.data-an"],
                timeout_seconds=1,
                retry_attempts=1,
                retry_delay_base_seconds=0,
            )

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["id"], "2605.12345")
        self.assertEqual(paper["title"], "RSS test paper")
        self.assertIn("RSS abstract text.", paper["summary"])
        self.assertIn("hep-ex", paper["categories"])
        self.assertIn("physics.data-an", paper["categories"])
        self.assertEqual(paper["authors"], ["ATLAS Collaboration"])


if __name__ == "__main__":
    unittest.main()
