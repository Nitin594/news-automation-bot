"""Unit tests for feed collector, conditional requests, retries, and error isolation."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest
import requests

from daily_tech_brief.collector import FeedCollector, FetchResult
from daily_tech_brief.models import SourceConfig

SAMPLE_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Tech Blog</title>
    <link>https://example.com</link>
    <description>Tech news and updates</description>
    <item>
      <title>Python 3.14 Alpha Released</title>
      <link>https://example.com/python-314-alpha</link>
      <description>The first alpha release of Python 3.14 is here.</description>
      <pubDate>Sun, 25 Oct 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Sample Atom Feed</title>
  <link href="https://example.com/atom"/>
  <updated>2026-10-25T08:00:00Z</updated>
  <entry>
    <title>Anthropic Announces Claude 3.5 Sonnet Update</title>
    <link href="https://example.com/claude-update"/>
    <id>urn:uuid:12345</id>
    <updated>2026-10-25T08:00:00Z</updated>
    <summary>Anthropic has updated Claude 3.5 Sonnet.</summary>
  </entry>
</feed>
"""


def test_fetch_valid_rss(sample_source: SourceConfig, ist_tz: ZoneInfo):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.headers = {"ETag": '"etag-rss"', "Last-Modified": "Sun, 25 Oct 2026 08:00:00 GMT"}
    mock_resp.iter_content.return_value = [SAMPLE_RSS_XML]
    session.get.return_value = mock_resp

    collector = FeedCollector([sample_source], ist_tz, session=session)
    res = collector.fetch_source(sample_source)

    assert res.status == "SUCCESS"
    assert res.articles_count == 1
    assert res.etag == '"etag-rss"'
    assert res.articles[0].title == "Python 3.14 Alpha Released"
    assert res.articles[0].canonical_url == "https://example.com/python-314-alpha"


def test_fetch_valid_atom(sample_source: SourceConfig, ist_tz: ZoneInfo):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.headers = {}
    mock_resp.iter_content.return_value = [SAMPLE_ATOM_XML]
    session.get.return_value = mock_resp

    collector = FeedCollector([sample_source], ist_tz, session=session)
    res = collector.fetch_source(sample_source)

    assert res.status == "SUCCESS"
    assert res.articles_count == 1
    assert "Claude" in res.articles[0].title


def test_fetch_304_not_modified(sample_source: SourceConfig, ist_tz: ZoneInfo):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 304
    session.get.return_value = mock_resp

    collector = FeedCollector([sample_source], ist_tz, session=session)
    res = collector.fetch_source(sample_source, cached_etag='"cached-etag"')

    assert res.status == "NOT_MODIFIED"
    assert res.articles_count == 0
    assert res.etag == '"cached-etag"'


def test_fetch_http_429_backoff(sample_source: SourceConfig, ist_tz: ZoneInfo):
    session = MagicMock()
    # First returns 429 with Retry-After: 0.1, then returns 200 with XML
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {"Retry-After": "0"}

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.ok = True
    mock_200.headers = {}
    mock_200.iter_content.return_value = [SAMPLE_RSS_XML]

    session.get.side_effect = [mock_429, mock_200]

    collector = FeedCollector([sample_source], ist_tz, session=session)
    res = collector.fetch_source(sample_source)

    assert res.status == "SUCCESS"
    assert res.articles_count == 1
    assert session.get.call_count == 2


def test_fetch_timeout(sample_source: SourceConfig, ist_tz: ZoneInfo):
    session = MagicMock()
    session.get.side_effect = requests.exceptions.Timeout("Connection timed out")

    collector = FeedCollector([sample_source], ist_tz, session=session)
    res = collector.fetch_source(sample_source)

    assert res.status == "TIMEOUT"
    assert res.articles_count == 0
    assert "timed out" in res.error_message


def test_fetch_malformed_xml(sample_source: SourceConfig, ist_tz: ZoneInfo):
    session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.headers = {}
    mock_resp.iter_content.return_value = [b"This is completely invalid XML <<>> & junk"]
    session.get.return_value = mock_resp

    collector = FeedCollector([sample_source], ist_tz, session=session)
    res = collector.fetch_source(sample_source)

    # Should not crash, returns EMPTY or PARSE_ERROR
    assert res.status in ("EMPTY", "PARSE_ERROR")
    assert res.articles_count == 0


def test_one_failed_source_other_succeeds(ist_tz: ZoneInfo):
    s1 = SourceConfig(id="s1_fail", name="Failing Source", url="https://fail.example.com/rss")
    s2 = SourceConfig(id="s2_ok", name="Working Source", url="https://ok.example.com/rss")

    session = MagicMock()
    # s1 fails with 500, s2 succeeds with XML
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.ok = False
    resp_500.reason = "Internal Server Error"

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.ok = True
    resp_200.headers = {}
    resp_200.iter_content.return_value = [SAMPLE_RSS_XML]

    def mock_get(url, **kwargs):
        if "fail" in url:
            return resp_500
        return resp_200

    session.get.side_effect = mock_get

    collector = FeedCollector([s1, s2], ist_tz, session=session)
    results = collector.fetch_all()

    assert len(results) == 2
    assert results[0].status == "HTTP_ERROR"
    assert results[1].status == "SUCCESS"
    assert results[1].articles_count == 1
