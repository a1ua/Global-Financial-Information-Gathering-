"""Bounded RSS 2.0 parsing without network, persistence or model calls."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree


MAX_FEED_BYTES = 5 * 1024 * 1024
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "table", "tr", "td", "th", "section", "h1", "h2", "h3", "blockquote"}


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden.append(tag)
        elif not self.hidden and tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if not self.hidden and tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain_text(value):
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _http_url(value):
    if not value or re.search(r"[\s\\]", value):
        raise ValueError("invalid_source_url")
    try:
        parts = urlsplit(value)
        valid = parts.scheme.lower() in {"http", "https"} and bool(parts.hostname)
        parts.port  # Validate malformed ports as well as malformed brackets.
    except ValueError as exc:
        raise ValueError("invalid_source_url") from exc
    if not valid:
        raise ValueError("invalid_source_url")
    return value


def _source_time(value):
    result = {
        "source_time_text": value or None,
        "source_published_at": None,
        "source_time_precision": "unknown",
        "source_timezone": None,
        "time_parse_status": "missing" if not value else "invalid",
    }
    if not value:
        return result
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return result
        result.update(source_time_precision="date", time_parse_status="date_only")
        return result
    try:
        stamp = parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError, OverflowError):
        return result
    clock = re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\b", value)
    if not clock:
        return result
    result["source_time_precision"] = "second" if clock.group(1) else "minute"
    # Keep the supplied RFC timezone token; do not guess an IANA location.
    suffix = value[clock.end():].strip().split()
    if suffix:
        result["source_timezone"] = suffix[0]
    if stamp.tzinfo is None:
        result["source_time_precision"] = "unknown"
        result["time_parse_status"] = "timezone_missing"
        return result
    result.update(
        source_published_at=stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        time_parse_status="parsed",
    )
    return result


def parse_rss(data: bytes, *, feed_url: str) -> list[dict]:
    """Parse RSS2 items or raise ValueError; never silently discard bad items.

    Required item fields are nonempty title and HTTP(S) link. Description,
    GUID and pubDate are optional. Duplicate records remain for ingestion to
    handle. RFC pubDate without a known timezone never becomes a UTC instant.
    """
    if not isinstance(data, bytes):
        raise TypeError("RSS data must be bytes")
    _http_url(feed_url)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed_too_large")
    # Removing NULs also detects declarations in UTF-16/UTF-32 encoded XML.
    declaration_scan = data.replace(b"\x00", b"")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", declaration_scan, re.IGNORECASE):
        raise ValueError("xml_declaration_forbidden")
    try:
        root = ElementTree.fromstring(data)
    except ValueError as exc:
        # Expat does not directly support these multibyte legacy encodings.
        encoding = re.match(br'''\s*<\?xml\b[^>]*\bencoding\s*=\s*['"]([^'"]+)['"]''', data)
        if not encoding or encoding.group(1).lower() not in {b"gb2312", b"gbk", b"big5"}:
            raise ValueError("unsupported_xml_encoding") from exc
        try:
            root = ElementTree.fromstring(data.decode(encoding.group(1).decode("ascii")))
        except (UnicodeError, ElementTree.ParseError) as decode_exc:
            raise ValueError("invalid_xml") from decode_exc
    except ElementTree.ParseError as exc:
        raise ValueError("invalid_xml") from exc
    if root.tag != "rss" or root.attrib.get("version") != "2.0":
        raise ValueError("unsupported_feed_format")
    channel = root.find("channel")
    if channel is None:
        raise ValueError("missing_channel")
    items = []
    for item in channel.findall("item"):
        title = _plain_text(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            raise ValueError("missing_item_field")
        if re.search(r"[\s\\]", link):
            raise ValueError("invalid_source_url")
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link):
            original_url = _http_url(link)
        else:
            original_url = _http_url(urljoin(feed_url, link))
        guid = (item.findtext("guid") or "").strip()
        source_time = (item.findtext("pubDate") or "").strip()
        items.append({
            "source_item_key": "guid:" + guid if guid else "link:" + original_url,
            "original_url": original_url,
            "title": title,
            "normalized_text": _plain_text(item.findtext("description") or ""),
            **_source_time(source_time),
        })
    return items
