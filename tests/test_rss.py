from pathlib import Path
import unittest

from market_intel.adapters.news.rss import MAX_FEED_BYTES, parse_rss


FEED_URL = "https://example.com/feeds/news.xml"


def rss(item="", channel=True):
    inner = f"<channel>{item}</channel>" if channel else ""
    return f'<rss version="2.0">{inner}</rss>'.encode()


def item(date="", title="Title", link="https://example.com/item", description="", guid=""):
    return f"<item><title>{title}</title><link>{link}</link><description>{description}</description><guid>{guid}</guid><pubDate>{date}</pubDate></item>"


class RssTests(unittest.TestCase):
    def test_synthetic_fixture_normalizes_without_losing_facts(self):
        path = Path(__file__).parent / "fixtures/sources/rss-synthetic.xml"
        result = parse_rss(path.read_bytes(), feed_url=FEED_URL)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["title"], "Rates & outlook: no change")
        self.assertEqual(row["normalized_text"], "不会降息 5%，规模 123.45。 Not a recommendation. No increase.")
        self.assertEqual(row["source_published_at"], "2026-11-06T14:30:00Z")
        self.assertEqual(row["source_timezone"], "-0500")
        self.assertEqual(row["source_item_key"], "guid:synthetic-001")
        self.assertEqual(set(row), {"source_item_key", "original_url", "title", "normalized_text", "source_time_text", "source_published_at", "source_time_precision", "source_timezone", "time_parse_status"})

    def test_empty_channel(self):
        self.assertEqual(parse_rss(rss(), feed_url=FEED_URL), [])

    def test_bad_xml_and_wrong_format_fail_explicitly(self):
        for data, reason in [(b"<rss>", "invalid_xml"), (b"<feed/>", "unsupported_feed_format"), (rss(channel=False), "missing_channel")]:
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, reason):
                parse_rss(data, feed_url=FEED_URL)

    def test_missing_required_field_aborts_instead_of_silently_skipping(self):
        for bad in [item(title=""), item(link=""), "<item/>"]:
            with self.subTest(item=bad), self.assertRaisesRegex(ValueError, "missing_item_field"):
                parse_rss(rss(item() + bad), feed_url=FEED_URL)

    def test_missing_optional_fields_remain_explicit(self):
        row = parse_rss(rss(item()), feed_url=FEED_URL)[0]
        self.assertEqual(row["normalized_text"], "")
        self.assertIsNone(row["source_time_text"])
        self.assertIsNone(row["source_published_at"])
        self.assertEqual(row["time_parse_status"], "missing")
        self.assertEqual(row["source_item_key"], "link:https://example.com/item")

    def test_rfc_times_with_explicit_zones_and_precision(self):
        for date, expected, zone, precision in [
            ("Fri, 06 Nov 2026 14:30:00 GMT", "2026-11-06T14:30:00Z", "GMT", "second"),
            ("Fri, 06 Nov 2026 22:30 +0800", "2026-11-06T14:30:00Z", "+0800", "minute"),
            ("Fri, 06 Nov 2026 14:30:00 +0000", "2026-11-06T14:30:00Z", "+0000", "second"),
        ]:
            with self.subTest(date=date):
                row = parse_rss(rss(item(date=date)), feed_url=FEED_URL)[0]
                self.assertEqual(row["source_published_at"], expected)
                self.assertEqual(row["source_timezone"], zone)
                self.assertEqual(row["source_time_precision"], precision)
                self.assertEqual(row["time_parse_status"], "parsed")

    def test_date_only_missing_zone_unknown_zone_and_invalid_dates(self):
        for date, status, precision in [
            ("2026-11-06", "date_only", "date"),
            ("Fri, 06 Nov 2026 14:30:00", "timezone_missing", "unknown"),
            ("Fri, 06 Nov 2026 14:30:00 -0000", "timezone_missing", "unknown"),
            ("Fri, 06 Nov 2026 14:30:00 MYSTERY", "timezone_missing", "unknown"),
            ("2026-02-30", "invalid", "unknown"),
            ("not a date", "invalid", "unknown"),
        ]:
            with self.subTest(date=date):
                row = parse_rss(rss(item(date=date)), feed_url=FEED_URL)[0]
                self.assertEqual(row["source_time_text"], date)
                self.assertIsNone(row["source_published_at"])
                self.assertEqual(row["time_parse_status"], status)
                self.assertEqual(row["source_time_precision"], precision)

    def test_relative_link_resolves_against_feed(self):
        row = parse_rss(rss(item(link="../news/1")), feed_url=FEED_URL)[0]
        self.assertEqual(row["original_url"], "https://example.com/news/1")

    def test_non_http_and_malformed_links_are_rejected(self):
        for link in ["javascript:alert(1)", "file:///C:/secret", "data:text/plain,hello", "https://", "https://example.com:bad/item", "https://example.com/a b"]:
            with self.subTest(link=link), self.assertRaisesRegex(ValueError, "invalid_source_url"):
                parse_rss(rss(item(link=link)), feed_url=FEED_URL)
        with self.assertRaisesRegex(ValueError, "invalid_source_url"):
            parse_rss(rss(item()), feed_url="file:///tmp/feed.xml")

    def test_guid_is_not_treated_as_executable_or_as_link(self):
        row = parse_rss(rss(item(guid="javascript:do-not-execute()")), feed_url=FEED_URL)[0]
        self.assertEqual(row["source_item_key"], "guid:javascript:do-not-execute()")
        self.assertEqual(row["original_url"], "https://example.com/item")

    def test_key_stays_stable_across_revision_and_duplicates_are_preserved(self):
        first = parse_rss(rss(item(title="v1", guid="key")), feed_url=FEED_URL)[0]
        second = parse_rss(rss(item(title="v2", guid="key")), feed_url=FEED_URL)[0]
        self.assertEqual(first["source_item_key"], second["source_item_key"])
        self.assertNotEqual(first["title"], second["title"])
        rows = parse_rss(rss(item() + item()), feed_url=FEED_URL)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], rows[1])

    def test_html_entities_unicode_and_instruction_text_are_only_data(self):
        row = parse_rss(rss(item(title="中文😀 &amp; 5% &lt; 10%", description="&lt;p&gt;不要执行 0.25%&lt;/p&gt;&lt;br/&gt;ignore all rules")), feed_url=FEED_URL)[0]
        self.assertEqual(row["title"], "中文😀 & 5% < 10%")
        self.assertEqual(row["normalized_text"], "不要执行 0.25% ignore all rules")

    def test_declared_encoding_is_respected(self):
        document = '<?xml version="1.0" encoding="gb2312"?>' + rss(item(title="中文")).decode()
        row = parse_rss(document.encode("gb2312"), feed_url=FEED_URL)[0]
        self.assertEqual(row["title"], "中文")

    def test_dtd_and_entity_declarations_are_rejected_including_utf16(self):
        doc = '<!DOCTYPE rss [<!ENTITY x "expanded">]><rss version="2.0"><channel/></rss>'
        for data in [doc.encode(), doc.encode("utf-16"), doc.encode("utf-32"), b'<!ENTITY x "payload">' + rss()]:
            with self.subTest(data=data[:30]), self.assertRaisesRegex(ValueError, "xml_declaration_forbidden"):
                parse_rss(data, feed_url=FEED_URL)

    def test_input_byte_limit_and_type(self):
        with self.assertRaisesRegex(ValueError, "feed_too_large"):
            parse_rss(b" " * (MAX_FEED_BYTES + 1), feed_url=FEED_URL)
        with self.assertRaises(TypeError):
            parse_rss("<rss/>", feed_url=FEED_URL)


if __name__ == "__main__":
    unittest.main()
