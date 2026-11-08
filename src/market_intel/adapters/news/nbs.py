"""Bounded NBS list metadata parser; no body downloads or persistence."""

from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit


MAX_PAGE_BYTES = 2 * 1024 * 1024
_ARTICLE_PATH = re.compile(r"/sj/zxfb/\d{6}/t[A-Za-z0-9_-]+\.html\Z")
_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def _page_url(value):
    try:
        parts = urlsplit(value)
        valid = parts.scheme == "https" and parts.netloc == "www.stats.gov.cn"
        valid = valid and parts.path == "/sj/zxfb/" and not parts.query and not parts.fragment
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("invalid_nbs_page_url")


def _article_url(value, page_url):
    if not value or re.search(r"[\s\\]", value):
        raise ValueError("invalid_nbs_article_url")
    try:
        absolute = urljoin(page_url, value)
        parts = urlsplit(absolute)
    except ValueError as exc:
        raise ValueError("invalid_nbs_article_url") from exc
    if not _ARTICLE_PATH.fullmatch(parts.path):
        return None  # Ordinary navigation or a different publication section.
    if parts.scheme != "https" or parts.netloc != "www.stats.gov.cn" or parts.query or parts.fragment:
        raise ValueError("invalid_nbs_article_url")
    return absolute


class _ListParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.items = []
        self.anchor = None
        self.lists = []
        self.hidden = []
        self.excluded = []
        self.div_depth = 0
        self.content_depths = []

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            return
        if tag in {"script", "style"}:
            self.hidden.append(tag)
            return
        if tag in {"header", "nav", "footer"}:
            self.excluded.append(tag)
        if tag == "div":
            self.div_depth += 1
            if "list-content" in (dict(attrs).get("class") or "").split():
                self.content_depths.append(self.div_depth)
        if tag in {"ul", "ol"}:
            self.lists.append(tag)
        elif tag == "li":
            self.items.append({"links": [], "text": [], "eligible": bool(self.lists) and bool(self.content_depths) and not self.excluded})
        elif tag == "a" and self.items:
            if self.anchor is not None:
                raise ValueError("malformed_nbs_list_html")
            self.anchor = {"href": dict(attrs).get("href"), "text": []}

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == "a" and self.items and self.anchor is not None:
            self.items[-1]["links"].append(self.anchor)
            self.anchor = None
        elif tag == "li":
            if not self.items or self.anchor is not None:
                raise ValueError("malformed_nbs_list_html")
            self.rows.append(self.items.pop())
        elif tag in {"ul", "ol"}:
            if not self.lists or self.lists.pop() != tag:
                raise ValueError("malformed_nbs_list_html")
        if tag in {"header", "nav", "footer"}:
            if self.excluded and self.excluded[-1] == tag:
                self.excluded.pop()
        if tag == "div":
            if self.content_depths and self.content_depths[-1] == self.div_depth:
                self.content_depths.pop()
            self.div_depth -= 1

    def handle_data(self, data):
        if self.hidden or not self.items:
            return
        if self.anchor is not None:
            self.anchor["text"].append(data)
        else:
            self.items[-1]["text"].append(data)


def parse_nbs_list(data: bytes, *, page_url: str) -> list[dict]:
    """Extract title/date metadata from dated list rows, never article bodies.

    Only li rows inside the observed div.list-content container are eligible.
    No official empty-list marker has been observed; zero matching entries is
    an explicit error, never a successful empty result.
    """
    _page_url(page_url)
    if not isinstance(data, bytes):
        raise TypeError("NBS page data must be bytes")
    if len(data) > MAX_PAGE_BYTES:
        raise ValueError("nbs_page_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid_nbs_page_encoding") from exc
    parser = _ListParser()
    parser.feed(text)
    parser.close()
    if parser.items or parser.anchor is not None or parser.lists or parser.hidden or parser.content_depths:
        raise ValueError("malformed_nbs_list_html")
    result = {}
    for row in parser.rows:
        if not row["eligible"]:
            continue
        links = {}
        for anchor in row["links"]:
            href = anchor["href"]
            if not href:
                continue
            url = _article_url(href, page_url)
            if url is not None:
                title = " ".join("".join(anchor["text"]).split())
                if len(title) > len(links.get(url, "")):
                    links[url] = title
                elif url not in links:
                    links[url] = title
        if not links:
            continue
        if len(links) != 1:
            raise ValueError("ambiguous_nbs_list_item")
        url, title = next(iter(links.items()))
        if not title:
            raise ValueError("missing_nbs_title")
        dates = _DATE.findall(" ".join(row["text"]))
        if len(dates) != 1:
            raise ValueError("missing_or_ambiguous_nbs_list_date")
        source_time = dates[0]
        try:
            date.fromisoformat(source_time)
        except ValueError as exc:
            raise ValueError("invalid_nbs_list_date") from exc
        record = {
            "source_item_key": "link:" + url,
            "original_url": url,
            "title": title,
            "normalized_text": title,
            "source_time_text": source_time,
            "source_published_at": None,
            "source_time_precision": "date",
            "source_timezone": None,
            "time_parse_status": "date_only",
        }
        if url in result and result[url] != record:
            raise ValueError("conflicting_nbs_duplicate")
        result[url] = record
    if not result:
        raise ValueError("no_verified_nbs_list_entries")
    return list(result.values())
