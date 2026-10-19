"""Parsers for the AI news feeds feature (inline fixtures, no network)."""

import unittest

from dududa_v3.features import feeds

JUYA_HTML = """<h1>AI 早报 2026-10-18</h1>
<p><strong>视频版</strong>：<a href="https://youtube.com/x">YouTube</a></p>
<h2 id="s1">概览</h2>
<h3 id="s2">要闻</h3>
<ul><li>DeepSeek 更新 V4.1 Flash 模型 <a href="https://a.example/1">↗</a> <code>#1</code></li>
<li>OpenCode 披露安全事件 <a href="https://a.example/2">↗</a> <code>#2</code></li></ul>
<h3 id="s3">开发生态</h3>
<ul><li>Codex 重置用量 <a href="https://a.example/3">↗</a> <code>#3</code></li></ul>
<hr>
<h2 id="s5">要闻</h2>
<h3 id="s6"><a href="https://a.example/1">DeepSeek 更新 V4.1 Flash 模型</a> <code>#1</code></h3>
<blockquote><strong>10月17日</strong>，<strong>DeepSeek</strong> 发布 <code>V4.1-Flash-1017</code>。价格不变。</blockquote>
<p>正文第一段。</p>
<h3 id="s7"><a href="https://a.example/2">OpenCode 披露安全事件</a> <code>#2</code></h3>
<blockquote><p>旧系统遭未经授权访问；用户需轮换密钥。</p></blockquote>
<h2 id="s8">开发生态</h2>
<h3 id="s9"><a href="https://a.example/3">Codex 重置用量</a> <code>#3</code></h3>
<blockquote>Tibo 宣布第 13 天完整重置用量限制，重置已于北京时间凌晨完成，所有用户都能感受到这个变化，这是一句非常非常长的话。</blockquote>
"""

JUYA_RSS = f"""<?xml version='1.0' encoding='utf-8'?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0"><channel><title>橘鸦AI早报</title>
<item><title>2026-10-17</title><link>https://daily.juya.uk/issues/2026-10-17/</link>
<content:encoded><![CDATA[<h2>概览</h2><h3>要闻</h3><ul><li>旧的一期 <code>#1</code></li></ul>]]></content:encoded></item>
<item><title>2026-10-18</title><link>https://daily.juya.uk/issues/2026-10-18/?utm_source=rss</link>
<content:encoded><![CDATA[{JUYA_HTML}]]></content:encoded></item>
</channel></rss>""".encode()

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>OpenAI News</title>
<item><title><![CDATA[Introducing &amp; testing]]></title><link>https://openai.com/index/x?utm_source=rss&amp;id=3#top</link>
<pubDate>Fri, 16 Oct 2026 19:00:00 GMT</pubDate><description><![CDATA[<p>Hello</p>]]></description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Anthropic</title>
<entry><title>Inside the lab</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc&amp;feature=share&amp;si=zz"/>
<published>2026-09-23T18:01:32+00:00</published></entry></feed>"""

ANTHROPIC_HTML = """<div><a href="/news/featured-one" class="FeaturedGrid"><h2 class="headline-4">Featured title</h2>
<span class="caption bold">Announcements</span><time class="date">Oct 6, 2026</time><p>Body text</p></a>
<ul><li><a href="/news/newer" class="PublicationList"><time class="date">Oct 15, 2026</time>
<span class="subject">Policy</span><span class="PublicationList__title body-3">Newer &amp; better</span></a></li>
<li><a href="/news/featured-one" class="PublicationList"><time>Oct 6, 2026</time><span class="title">Featured title</span></a></li>
<li><a href="/research/other">Not news</a></li></ul></div>"""


class JuyaTests(unittest.TestCase):
    def test_issue_overview_with_summaries(self):
        items = feeds.parse_juya_issue(JUYA_HTML)
        self.assertEqual([item["num"] for item in items], [1, 2, 3])
        self.assertEqual(items[0]["category"], "要闻")
        self.assertEqual(items[2]["category"], "开发生态")
        self.assertEqual(items[0]["title"], "DeepSeek 更新 V4.1 Flash 模型")
        self.assertEqual(items[0]["summary"], "10月17日，DeepSeek 发布 V4.1-Flash-1017。")
        self.assertEqual(items[1]["summary"], "旧系统遭未经授权访问；")
        self.assertTrue(items[2]["summary"].endswith("…"))
        self.assertLessEqual(len(items[2]["summary"]), feeds.SUMMARY_CHARS)

    def test_feed_picks_newest_and_cleans_link(self):
        issues = feeds.parse_juya_feed(JUYA_RSS)
        self.assertEqual([issue["date"] for issue in issues], ["2026-10-18", "2026-10-17"])
        self.assertEqual(issues[0]["link"], "https://daily.juya.uk/issues/2026-10-18/")

    def test_format_marks_stale_issue_and_respects_limit(self):
        issue = feeds.parse_juya_feed(JUYA_RSS)[0]
        today = feeds.format_issue(issue, "2026-10-18")
        self.assertTrue(today.startswith("【橘鸦AI早报 2026-10-18】"))
        self.assertIn("◆ 开发生态", today)
        self.assertTrue(today.endswith("原文：https://daily.juya.uk/issues/2026-10-18/"))
        stale = feeds.format_issue(issue, "2026-10-19")
        self.assertIn("今天（2026-10-19）的早报还没出", stale)
        many = {"date": "2026-10-18", "link": "https://x", "items": [
            {"num": n, "category": "要闻" if n < 3 else "其他", "title": "标题" * 10, "summary": "摘要" * 25}
            for n in range(1, 41)]}
        text = feeds.format_issue(many, "2026-10-18")
        self.assertLessEqual(len(text), feeds.OVERVIEW_LIMIT)
        self.assertNotIn("另有", text)                        # Titles of every item fit…
        self.assertIn("摘要", text.split("◆ 其他")[0])        # …the lead section keeps summaries…
        self.assertNotIn("摘要", text.split("◆ 其他")[1])     # …the rest collapses to titles.
        many["items"] *= 3
        text = feeds.format_issue(many, "2026-10-18")
        self.assertLessEqual(len(text), feeds.OVERVIEW_LIMIT)
        self.assertIn("另有", text)


class UpdatesTests(unittest.TestCase):
    def test_rss(self):
        [item] = feeds.parse_feed(RSS)
        self.assertEqual(item["title"], "Introducing & testing")
        self.assertEqual(item["link"], "https://openai.com/index/x?id=3")
        self.assertEqual(item["date"], "2026-10-16")
        self.assertEqual(item["summary"], "Hello")

    def test_atom_keeps_video_id(self):
        [item] = feeds.parse_feed(ATOM)
        self.assertEqual(item["link"], "https://www.youtube.com/watch?v=abc&feature=share")
        self.assertEqual(item["date"], "2026-09-23")

    def test_anthropic_news_dedupes_and_sorts(self):
        items = feeds.parse_anthropic_news(ANTHROPIC_HTML)
        self.assertEqual([(i["title"], i["date"]) for i in items],
                         [("Newer & better", "2026-10-15"), ("Featured title", "2026-10-06")])
        self.assertEqual(items[0]["link"], "https://www.anthropic.com/news/newer")

    def test_company_aliases(self):
        for word in ("OpenAI", "o/", "O\\", "oai"):
            self.assertEqual(feeds.parse_company(word), "openai")
        for word in ("Anthropic", "A/", "a\\", "claude"):
            self.assertEqual(feeds.parse_company(word), "anthropic")
        self.assertIsNone(feeds.parse_company("google"))
        self.assertIsNone(feeds.parse_company(""))


if __name__ == "__main__":
    unittest.main()
