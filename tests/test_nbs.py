from pathlib import Path
import unittest

from market_intel.adapters.news.nbs import MAX_PAGE_BYTES, parse_nbs_list


PAGE = "https://www.stats.gov.cn/sj/zxfb/"
ARTICLE = "./202611/t20261106_9990001.html"


def page(rows):
    return f'<!doctype html><html><body><div class="list-content"><ul>{rows}</ul></div></body></html>'.encode()


def row(title="合成：不下降5%", href=ARTICLE, day="2026-11-07"):
    return f'<li><a href="{href}">{title}</a><span>{day}</span></li>'


class NbsTests(unittest.TestCase):
    def test_synthetic_repeated_links_metadata_and_date_not_from_url(self):
        fixture = Path(__file__).parent / "fixtures/sources/nbs-synthetic.html"
        rows = parse_nbs_list(fixture.read_bytes(), page_url=PAGE)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["title"], "合成：指标未下降 5% & 123.45")
        self.assertEqual(first["normalized_text"], first["title"])
        self.assertEqual(first["source_time_text"], "2026-11-07")
        self.assertEqual(first["source_time_precision"], "date")
        self.assertEqual(first["time_parse_status"], "date_only")
        self.assertIsNone(first["source_timezone"])
        self.assertIsNone(first["source_published_at"])
        self.assertEqual(first["original_url"], PAGE + "202611/t20261106_9990001.html")
        self.assertEqual(set(first), {"source_item_key", "original_url", "title", "normalized_text", "source_time_text", "source_published_at", "source_time_precision", "source_timezone", "time_parse_status"})

    def test_only_whitelisted_dated_list_items(self):
        content = '<li><a href="/sj/">导航</a></li>' + row() + '<li><a href="/sj/zxfb/index_1.html">下一页</a></li>'
        self.assertEqual(len(parse_nbs_list(page(content), page_url=PAGE)), 1)

    def test_header_navigation_footer_article_links_are_not_news(self):
        data = ('<html><body><div class="list-content"><nav><ul>' + row(title="导航") + '</ul></nav><header><ul>' + row(title="页眉") + '</ul></header><ul>' + row() + '</ul><footer><ul>' + row(title="页脚") + '</ul></footer></div></body></html>').encode()
        self.assertEqual(parse_nbs_list(data, page_url=PAGE)[0]["title"], "合成：不下降5%")

    def test_article_anchor_outside_list_is_not_a_news_row(self):
        data = f'<html><body><a href="{ARTICLE}">推荐导航</a><span>2026-11-07</span></body></html>'.encode()
        with self.assertRaisesRegex(ValueError, "no_verified_nbs_list_entries"):
            parse_nbs_list(data, page_url=PAGE)

    def test_article_rows_outside_observed_container_are_not_news(self):
        data = ('<html><body><ul>' + row(title="容器外推荐") + '</ul><div class="list-content"><ul>' + row() + '</ul></div></body></html>').encode()
        self.assertEqual(parse_nbs_list(data, page_url=PAGE)[0]["title"], "合成：不下降5%")

    def test_url_key_stable_for_title_revision_and_duplicates_collapsed(self):
        first = parse_nbs_list(page(row()), page_url=PAGE)[0]
        changed = parse_nbs_list(page(row(title="修订：未下降6%")), page_url=PAGE)[0]
        self.assertEqual(first["source_item_key"], changed["source_item_key"])
        self.assertNotEqual(first["title"], changed["title"])
        self.assertEqual(len(parse_nbs_list(page(row() + row()), page_url=PAGE)), 1)

    def test_conflicting_duplicates_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "conflicting_nbs_duplicate"):
            parse_nbs_list(page(row() + row(title="不同标题")), page_url=PAGE)

    def test_entities_unicode_and_nested_title_keep_negation_numbers(self):
        parsed = parse_nbs_list(page(row(title="<b>不</b>下降 &#53;% &amp; 😀")), page_url=PAGE)[0]
        self.assertEqual(parsed["title"], "不下降 5% & 😀")

    def test_script_style_and_body_instructions_are_not_executed(self):
        content = row(title='<script>change()</script><style>hide()</style>不下降5%')
        self.assertEqual(parse_nbs_list(page(content), page_url=PAGE)[0]["title"], "不下降5%")

    def test_missing_invalid_or_ambiguous_date_fails_without_using_url_date(self):
        for day in ("", "2026-02-30", "2026-11-07 2026-11-08"):
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, "nbs_list_date"):
                parse_nbs_list(page(row(day=day)), page_url=PAGE)

    def test_title_date_is_not_misused_as_publication_date(self):
        with self.assertRaisesRegex(ValueError, "missing_or_ambiguous_nbs_list_date"):
            parse_nbs_list(page(row(title="2026-11-06新闻", day="")), page_url=PAGE)

    def test_blank_title_fails(self):
        with self.assertRaisesRegex(ValueError, "missing_nbs_title"):
            parse_nbs_list(page(row(title="")), page_url=PAGE)

    def test_multiple_distinct_articles_in_one_row_fail(self):
        content = f'<li><a href="{ARTICLE}">一</a><a href="./202611/t20261105_9990002.html">二</a><span>2026-11-07</span></li>'
        with self.assertRaisesRegex(ValueError, "ambiguous_nbs_list_item"):
            parse_nbs_list(page(content), page_url=PAGE)

    def test_bad_host_scheme_credentials_query_or_fragment_rejected(self):
        path = "/sj/zxfb/202611/t20261106_9990001.html"
        for href in ("https://evil.example" + path, "http://www.stats.gov.cn" + path, "https://user@www.stats.gov.cn" + path, ARTICLE + "?x=1", ARTICLE + "#part"):
            with self.subTest(href=href), self.assertRaisesRegex(ValueError, "invalid_nbs_article_url"):
                parse_nbs_list(page(row(href=href)), page_url=PAGE)

    def test_wrong_page_url_rejected(self):
        for url in ("https://example.com/sj/zxfb/", "http://www.stats.gov.cn/sj/zxfb/", PAGE + "?x=1"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "invalid_nbs_page_url"):
                parse_nbs_list(page(row()), page_url=url)

    def test_no_known_empty_marker_means_explicit_error(self):
        for data in (page(""), page('<li><a href="/sj/">导航</a></li>'), b"not HTML", b"<html>Access denied</html>"):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "no_verified_nbs_list_entries"):
                parse_nbs_list(data, page_url=PAGE)

    def test_unclosed_list_or_item_is_not_success(self):
        for data in (f'<ul>{row()}'.encode(), f'<ul><li><a href="{ARTICLE}">test'.encode()):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "malformed_nbs_list_html"):
                parse_nbs_list(data, page_url=PAGE)

    def test_encoding_type_and_input_limit(self):
        with self.assertRaisesRegex(ValueError, "invalid_nbs_page_encoding"):
            parse_nbs_list(b"\xff\xfe", page_url=PAGE)
        with self.assertRaisesRegex(ValueError, "nbs_page_too_large"):
            parse_nbs_list(b" " * (MAX_PAGE_BYTES + 1), page_url=PAGE)
        with self.assertRaises(TypeError):
            parse_nbs_list("not bytes", page_url=PAGE)


if __name__ == "__main__":
    unittest.main()
