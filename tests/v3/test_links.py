"""Link preview parsing and observer behaviour; network is replaced by inline fixtures."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dududa_v3.features import links
from dududa_v3.features.base import FeatureError, Inbound, Sender

WECHAT_HTML = """<html><head>
<meta property="og:title" content="og 标题" />
<meta property="og:image" content="https://mmbiz.qpic.cn/og.jpg" />
<meta property="og:description" content="og 描述" />
</head><body><script>
var nickname = htmlDecode("中国科大研究生会");
var msg_title = '「美丽邂逅」主持人&amp;故事征集\\x26更多'.html(false);
var msg_desc = htmlDecode("人海很大，等你溯光而来。");
var msg_cdn_url = "https://mmbiz.qpic.cn/cover.jpg?wx_fmt=jpeg";
var ct = "1790760000";
</script></body></html>"""

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2610.13139v1</id>
    <title>Strict Dirichlet P\\'olya Inequality
      for Simply Connected Planar Domains</title>
    <summary>  We establish the strict inequality on every bounded domain. As a consequence we get more.
    </summary>
    <author><name>Quanyu Tang</name></author>
    <author><name>Zuoqin Wang</name></author>
    <author><name>A Third</name></author>
    <author><name>A Fourth</name></author>
    <arxiv:primary_category term="math.AP" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

ARXIV_PAGE = """<html><head>
<meta name="citation_title" content="Attention Is All You Need" />
<meta name="citation_author" content="Vaswani, Ashish" />
<meta name="citation_author" content="Shazeer, Noam" />
<meta name="citation_abstract" content="The dominant models are complex. We propose the Transformer." />
</head></html>"""

GENERIC_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Fallback title</title>
<meta content="The Daily" property="og:title">
<meta property="og:site_name" content="Apple Podcasts">
<meta name="description" content="Daily News Podcast · Updated Daily">
<meta property="og:image" content="/artwork.jpg">
<link rel="canonical" href="https://podcasts.apple.com/us/podcast/the-daily/id1200361736">
</head><body>ignored</body></html>"""


def inbound(text, segments=(), conversation="qq-1:group:100"):
    return Inbound(account_id="qq-1", conversation_id=conversation, message_id="m1", text=text,
                   sender=Sender(id="7"), segments=list(segments))


class UrlTests(unittest.TestCase):
    def test_find_urls_trims_punctuation_and_handles_cjk_and_bare_hosts(self):
        text = ("看这个https://arxiv.org/abs/2610.13139，还有(https://en.wikipedia.org/wiki/Foo_(bar)). "
                "口令 xhslink.com/m/1gJ5tOG6M1b 复制后打开 b23.tv/abc123")
        self.assertEqual(links.find_urls(text), [
            "https://arxiv.org/abs/2610.13139", "https://en.wikipedia.org/wiki/Foo_(bar)",
            "https://xhslink.com/m/1gJ5tOG6M1b", "https://b23.tv/abc123"])

    def test_clean_url_strips_tracking_but_keeps_meaningful_params(self):
        self.assertEqual(links.clean_url(
            "https://www.bilibili.com/video/BV1qYpN6vE7J/?p=2&share_source=copy_web&vd_source=abc&spm_id_from=333"
            "&from=search&mid=1&unique_k=x"), "https://www.bilibili.com/video/BV1qYpN6vE7J?p=2")
        self.assertEqual(links.clean_url("https://example.com/a?id=3&utm_source=x&t=40&xsec_token=y#rd"),
                         "https://example.com/a?id=3&t=40")
        self.assertEqual(links.clean_url("https://x.com/a/status/1?s=20&t=abc"), "https://x.com/a/status/1")

    def test_skip_rules(self):
        for url in ("https://www.xiaohongshu.com/explore/abc", "http://xhslink.com/m/x", "https://qun.qq.com/x",
                    "https://multimedia.nt.qq.com.cn/download", "http://127.0.0.1:8783/v3/runs",
                    "http://192.168.1.1/", "http://[::1]/", "http://localhost/"):
            self.assertTrue(links.should_skip(url), url)
        for url in ("https://mp.weixin.qq.com/s/abc", "https://www.bilibili.com/video/BV1qYpN6vE7J",
                    "https://198.18.0.5/"):
            self.assertFalse(links.should_skip(url), url)

    def test_message_links_prefers_card_hint_and_dedupes(self):
        message = inbound("[卡片] https://b23.tv/ipDDjmV?share_medium=android&bbid=1", [
            {"type": "light_app", "title": "Arcaea 速成", "description": "哔哩哔哩专栏",
             "url": "https://b23.tv/ipDDjmV?share_medium=android&share_source=qq&bbid=XX&ts=1"},
            {"type": "text", "text": "顺便 https://arxiv.org/abs/2610.13139"}])
        found = links.message_links(message)
        self.assertEqual([(l.url.split("?")[0], l.hint_title) for l in found],
                         [("https://b23.tv/ipDDjmV", "Arcaea 速成"), ("https://arxiv.org/abs/2610.13139", "")])


class ParserTests(unittest.TestCase):
    def test_bilibili_ids_and_view(self):
        self.assertEqual(links.bilibili_video_id("https://m.bilibili.com/video/BV1qYpN6vE7J?p=1"),
                         ("bvid", "BV1qYpN6vE7J"))
        self.assertEqual(links.bilibili_video_id("https://www.bilibili.com/video/av170001/"), ("aid", "170001"))
        self.assertIsNone(links.bilibili_video_id("https://www.bilibili.com/opus/1260437262033747971"))
        preview = links.parse_bilibili_view({"code": 0, "data": {
            "bvid": "BV1qYpN6vE7J", "title": "反方向的钟", "pic": "http://i0.hdslb.com/bfs/archive/a.jpg",
            "duration": 3725, "owner": {"name": "茶茶茶先森"}, "stat": {"view": 1348149}}},
            "https://www.bilibili.com/video/BV1qYpN6vE7J?p=3")
        self.assertEqual(preview.text, "【B站】反方向的钟\nUP主 茶茶茶先森 · 1:02:05 · 134.8万播放\n"
                                       "https://www.bilibili.com/video/BV1qYpN6vE7J?p=3")
        self.assertEqual(preview.image_url, "http://i0.hdslb.com/bfs/archive/a.jpg@640w_400h_1c.jpg")
        self.assertIsNone(links.parse_bilibili_view({"code": -404, "message": "啥都木有"}, ""))

    def test_bilibili_space(self):
        self.assertEqual(links.bilibili_space_mid("https://m.bilibili.com/space/3494362707135250?x=1"),
                         "3494362707135250")
        self.assertEqual(links.bilibili_space_mid("https://space.bilibili.com/42/video"), "42")
        preview = links.parse_bilibili_card({"code": 0, "data": {"card": {
            "name": "比特新语", "fans": 612081, "sign": "讲未曾见过的故事", "face": "https://i1.hdslb.com/f.jpg"}}}, "42")
        self.assertEqual(preview.text, "【B站】UP主 比特新语\n粉丝 61.2万 · 讲未曾见过的故事\nhttps://space.bilibili.com/42")

    def test_wechat(self):
        preview = links.parse_wechat(WECHAT_HTML, "https://mp.weixin.qq.com/s?__biz=MzA&mid=22&idx=1&sn=ab&chksm=z"
                                                  "&scene=21#wechat_redirect")
        self.assertEqual(preview.title, "「美丽邂逅」主持人&故事征集&更多")
        self.assertEqual(preview.lines[0], "中国科大研究生会 · " + links._date(1790760000))
        self.assertEqual(preview.lines[1], "人海很大，等你溯光而来。")
        self.assertEqual(preview.url, "https://mp.weixin.qq.com/s?__biz=MzA&mid=22&idx=1&sn=ab")
        self.assertEqual(preview.image_url, "https://mmbiz.qpic.cn/cover.jpg?wx_fmt=jpeg")
        self.assertIsNone(links.parse_wechat("<html><head><title>环境异常</title>"
                                             "<meta property='og:title' content='环境异常'></head></html>",
                                             "https://mp.weixin.qq.com/s/x"))

    def test_twitter(self):
        self.assertEqual(links.twitter_status("https://twitter.com/elonmusk/status/158534198?s=20"), "158534198")
        self.assertEqual(links.twitter_status("https://x.com/i/web/status/99"), "99")
        self.assertIsNone(links.twitter_status("https://x.com/elonmusk"))
        preview = links.parse_fxtwitter({"code": 200, "tweet": {
            "id": "158", "text": "Entering Twitter HQ", "likes": 1219785, "created_timestamp": 1666809958,
            "author": {"name": "Elon Musk", "screen_name": "elonmusk"},
            "media": {"photos": [{"url": "https://pbs.twimg.com/media/A.jpg"}, {"url": "https://pbs.twimg.com/b"}]}}})
        self.assertEqual(preview.title, "Elon Musk (@elonmusk)")
        self.assertEqual(preview.url, "https://x.com/elonmusk/status/158")
        self.assertIn("2图 · ♥122万", preview.lines[1])
        self.assertEqual(preview.image_url, "https://pbs.twimg.com/media/A.jpg?name=small")
        self.assertIsNone(links.parse_fxtwitter({"code": 404, "message": "NOT_FOUND"}))

    def test_arxiv(self):
        for url, expected in (("https://arxiv.org/abs/2610.13139", "2610.13139"),
                              ("https://arxiv.org/pdf/2610.13139v2.pdf", "2610.13139v2"),
                              ("https://www.arxiv.org/html/2401.00001v1/", "2401.00001v1"),
                              ("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"),
                              ("https://arxiv.org/list/cs.AI/recent", None)):
            self.assertEqual(links.arxiv_id(url), expected, url)
        preview = links.parse_arxiv_atom(ARXIV_ATOM, "2610.13139")
        self.assertEqual(preview.text, "【arXiv】Strict Dirichlet P\\'olya Inequality for Simply Connected Planar "
                                       "Domains\nQuanyu Tang, Zuoqin Wang, A Third et al. · math.AP\n"
                                       "We establish the strict inequality on every bounded domain.\n"
                                       "https://arxiv.org/abs/2610.13139")
        self.assertIsNone(links.parse_arxiv_atom("<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Error"
                                                 "</title></entry></feed>", "x"))
        page = links.parse_arxiv_page(ARXIV_PAGE, "1706.03762")
        self.assertEqual(page.lines, ["Ashish Vaswani, Noam Shazeer", "The dominant models are complex."])

    def test_rxiv_and_crossref(self):
        self.assertEqual(links.rxiv_doi("https://www.biorxiv.org/content/10.1101/2023.12.20.572539v2.full"),
                         ("biorxiv", "10.1101/2023.12.20.572539"))
        self.assertEqual(links.rxiv_doi("https://www.medrxiv.org/content/10.1101/2020.03.05.20031088v1"),
                         ("medrxiv", "10.1101/2020.03.05.20031088"))
        preview = links.parse_rxiv({"collection": [
            {"title": "Old", "version": "1"},
            {"title": "The cryo-EM structure of ASK1", "authors": "Honzejkova, K.; Kosek, D.",
             "doi": "10.1101/2023.12.20.572539", "date": "2024-02-14", "version": "2",
             "category": "biochemistry", "abstract": "ASK1 is a sensor. More text."}]}, "biorxiv")
        self.assertEqual(preview.text, "【bioRxiv】The cryo-EM structure of ASK1\nK. Honzejkova, D. Kosek · "
                                       "2024-02-14 · biochemistry\nASK1 is a sensor.\n"
                                       "https://www.biorxiv.org/content/10.1101/2023.12.20.572539v2")
        crossref = links.parse_crossref({"message": {
            "title": ["Accurate prediction"], "author": [{"given": "Minkyung", "family": "Baek"}],
            "container-title": ["Science"], "published": {"date-parts": [[2021, 8, 20]]},
            "abstract": "<jats:title>Deep learning</jats:title><jats:p>In 1972, X won. Then more.</jats:p>"}},
            "Science", "https://www.science.org/doi/10.1126/science.abj8754")
        self.assertEqual(crossref.lines, ["Minkyung Baek · Science · 2021-08-20", "In 1972, X won."])

    def test_generic(self):
        preview = links.parse_generic(GENERIC_HTML, "https://podcasts.apple.com/us/podcast/the-daily/id1200361736"
                                                    "?utm_source=x")
        self.assertEqual(preview.text, "【播客】The Daily\nDaily News Podcast · Updated Daily\n"
                                       "https://podcasts.apple.com/us/podcast/the-daily/id1200361736")
        self.assertEqual(preview.image_url, "https://podcasts.apple.com/artwork.jpg")
        blog = links.parse_generic("<html><head><title>My Blog Post</title>"
                                   "<meta property='og:site_name' content='Example Blog'></head></html>",
                                   "https://blog.example.com/p/1")
        self.assertEqual((blog.label, blog.title, blog.image_url), ("Example Blog", "My Blog Post", None))
        self.assertIsNone(links.parse_generic("<title>验证码_哔哩哔哩</title>", "https://www.bilibili.com/opus/1"))
        self.assertIsNone(links.parse_generic("<title>Just a moment...</title>", "https://www.science.org/x"))

    def test_decode_html_charset(self):
        body = "<meta charset='gbk'><title>中文</title>".encode("gbk")
        self.assertIn("中文", links.decode_html(body))


class ObserverTests(unittest.TestCase):
    def setUp(self):
        links._recent.clear()
        self.calls = []

    def ctx(self, message, pages):
        async def fetch(url, **kwargs):
            self.calls.append(url)
            for prefix, response in pages.items():
                if url.startswith(prefix):
                    if isinstance(response, Exception):
                        raise response
                    return response
            raise FeatureError("请求失败（HTTP 404）")

        async def fetch_json(url, **kwargs):
            body, _, _ = await fetch(url, **kwargs)
            return json.loads(body)

        return SimpleNamespace(inbound=message, config=lambda name: {}, fetch=fetch, fetch_json=fetch_json)

    def run_observer(self, ctx):
        with patch.object(links, "_resolves_internal", return_value=False):
            return asyncio.run(links.link_preview(ctx))

    def test_preview_with_cover_dedupe_and_limit(self):
        view = json.dumps({"code": 0, "data": {"bvid": "BV1qYpN6vE7J", "title": "反方向的钟", "duration": 267,
                                               "pic": "http://i0.hdslb.com/a.jpg", "owner": {"name": "UP"},
                                               "stat": {"view": 12}}}).encode()
        jpeg = b"\xff\xd8\xff\xe0" + b"0" * 64
        pages = {"https://api.bilibili.com/x/web-interface/view": (view, {}, ""),
                 "http://i0.hdslb.com/a.jpg": (jpeg, {"content-type": "image/jpeg"}, "")}
        text = ("https://www.bilibili.com/video/BV1qYpN6vE7J/?vd_source=1 "
                "https://www.bilibili.com/video/BV1qYpN6vE7J?spm_id_from=2 https://qun.qq.com/x "
                "https://a.example/1 https://b.example/2 https://c.example/3")
        reply = self.run_observer(self.ctx(inbound(text), pages))
        self.assertEqual([a["type"] for a in reply.actions], ["text", "image"])
        self.assertEqual(reply.actions[0]["text"], "【B站】反方向的钟\nUP主 UP · 4:27 · 12播放\n"
                                                   "https://www.bilibili.com/video/BV1qYpN6vE7J")
        self.assertEqual(reply.actions[1]["mime"], "image/jpeg")
        # Max three candidates: the bilibili link and two generic ones; the third generic link is never fetched.
        self.assertNotIn("https://c.example/3", self.calls)
        self.calls.clear()
        self.assertIsNone(self.run_observer(self.ctx(inbound("again https://www.bilibili.com/video/BV1qYpN6vE7J"),
                                                     pages)))
        self.assertEqual(self.calls, [])
        other = inbound("https://www.bilibili.com/video/BV1qYpN6vE7J", conversation="qq-1:group:200")
        self.assertIsNotNone(self.run_observer(self.ctx(other, pages)))

    def test_card_hint_fallback_when_fetch_fails(self):
        message = inbound("[卡片]", [{"type": "light_app", "title": "Arcaea 速成", "description": "哔哩哔哩专栏",
                                      "url": "https://b23.tv/ipDDjmV?share_source=qq&bbid=1"}])
        reply = self.run_observer(self.ctx(message, {"https://b23.tv/": FeatureError("请求失败（HTTP 412）")}))
        self.assertEqual(reply.actions, [{"type": "text", "text": "【B站】Arcaea 速成\n哔哩哔哩专栏\nhttps://b23.tv/ipDDjmV"}])

    def test_oversized_cover_is_skipped(self):
        page = (b"<html><head><meta property='og:title' content='Post'>"
                b"<meta property='og:image' content='https://blog.example/c.jpg'></head></html>")
        reply = self.run_observer(self.ctx(inbound("https://blog.example/post"), {
            "https://blog.example/post": (page, {"content-type": "text/html"}, "https://blog.example/post"),
            "https://blog.example/c.jpg": FeatureError("响应过大")}))
        self.assertEqual(reply.actions, [{"type": "text", "text": "【blog.example】Post\nhttps://blog.example/post"}])


if __name__ == "__main__":
    unittest.main()
