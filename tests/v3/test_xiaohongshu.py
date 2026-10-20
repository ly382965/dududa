"""Xiaohongshu note parsing, archiving and the observer; network is replaced by inline fixtures."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dududa_v3.features import xiaohongshu as xhs
from dududa_v3.features.base import FeatureError, Inbound, Sender

NOTE_ID = "6a433bae000000002103f5ef"
TOKEN = "CBnUvZ3vM8Dr="
SHARE = (f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}?app_platform=android&xsec_source=app_share"
         f"&xsec_token={TOKEN.replace('=', '%3D')}&author_share=1&xhsshare=QQ")

MOBILE_STATE = """{"global":{"appSettings":{"x":undefined}},"noteData":{"routeQuery":{},"data":{"noteData":{
"type":"normal","noteId":"NOTE_ID","title":"中科大读博礼物","desc":"硕转博成功[笑哭R]\\n#中科大[话题]# #读博日常[话题]#",
"time":1782791060000,"ipLocation":undefined,
"user":{"userId":"646a","nickName":"飞翔的托妞","avatar":"x"},
"interactInfo":{"likedCount":"236","collectedCount":"26","commentCount":"78","shareCount":"1.3万"},
"tagList":[{"type":"topic","name":"中科大"},{"type":"topic","name":"读博日常"},{"type":"topic","name":"modely"}],
"imageList":[
 {"infoList":[{"imageScene":"H5_DTL","url":"http://sns-webpic-qc.xhscdn.com/202610190121/3ec1848946058d3d2032a22b199cdfb4/1040g2sg326e4atod4a105o6s1fog8pk1gafanh0!h5_1080jpg"}],
  "url":"http://sns-webpic-qc.xhscdn.com/202610190121/3ec1848946058d3d2032a22b199cdfb4/1040g2sg326e4atod4a105o6s1fog8pk1gafanh0!h5_1080jpg",
  "livePhoto":false,"stream":{}},
 {"url":"http://sns-webpic-qc.xhscdn.com/202610190121/0123456789abcdef0123456789abcdef/spectrum/1040g0k0aaa!h5_1080jpg",
  "livePhoto":true,"stream":{"h264":[{"masterUrl":"http://sns-video-v3.xhscdn.com/live.mp4"}]}}
]}}}}""".replace("NOTE_ID", NOTE_ID)

DESKTOP_STATE = {"note": {"firstNoteId": "abc", "noteDetailMap": {"6ad42e1f0000000031006d38": {"note": {
    "noteId": "6ad42e1f0000000031006d38", "type": "video", "title": "", "desc": "第一行标题\n正文 #法国[话题]#",
    "user": {"nickname": "橙柿互动", "userId": "5c3a"}, "ipLocation": "浙江", "time": 1792290335000,
    "interactInfo": {"likedCount": "3032", "collectedCount": "791", "commentCount": "129", "shareCount": "10"},
    "tagList": [], "xsecToken": "TOK",
    "imageList": [{"urlDefault": "http://sns-webpic-qc.xhscdn.com/202403211626/c4fcecea4bd012a1fe8d2f1968d6aa91/110/0/01e50c1c!nd_dft_wlteh_webp_3",
                   "urlPre": "http://x/y", "infoList": []}],
    "video": {"consumer": {"originVideoKey": "spectrum/origin"},
              "media": {"stream": {"h264": [{"masterUrl": "http://sns-video-v3.xhscdn.com/h264.mp4",
                                              "backupUrls": ["http://sns-bak-v1.xhscdn.com/h264.mp4"]}],
                                   "h265": []}}}}}}}}


def page(state_json: str) -> str:
    return f"<html><head></head><body><script>window.__INITIAL_STATE__={state_json}</script></body></html>"


class ParserTests(unittest.TestCase):
    def test_links_and_refs(self):
        self.assertTrue(xhs.is_xhs_link("http://xhslink.com/m/7i4ACv0Q0sS"))
        self.assertTrue(xhs.is_xhs_link(SHARE))
        self.assertTrue(xhs.is_xhs_link(f"https://www.xiaohongshu.com/explore/{NOTE_ID}"))
        self.assertFalse(xhs.is_xhs_link("https://www.xiaohongshu.com/user/profile/647ca4d10000000010034c6d"))
        self.assertEqual(xhs.note_ref(SHARE), (NOTE_ID, TOKEN))
        blocked = ("https://www.xiaohongshu.com/404/sec_X?source=xhs_sec_server&originalUrl=http%3A%2F%2Fwww."
                   f"xiaohongshu.com%2Fdiscovery%2Fitem%2F{NOTE_ID}%3Fxsec_token%3DABC%253D")
        self.assertEqual(xhs.note_ref(blocked), (NOTE_ID, "ABC="))
        login = f"https://www.xiaohongshu.com/login?redirectPath=%2Fexplore%2F{NOTE_ID}"
        self.assertEqual(xhs.note_ref(login), (NOTE_ID, ""))
        self.assertIsNone(xhs.note_ref("https://www.xiaohongshu.com/"))

    def test_initial_state_with_undefined(self):
        state = xhs.parse_initial_state(page(MOBILE_STATE))
        self.assertIsNone(state["global"]["appSettings"]["x"])
        self.assertIsNone(xhs.parse_initial_state("<html>no state</html>"))
        self.assertIsNone(xhs.parse_initial_state(page("{broken")))

    def test_mobile_note(self):
        note = xhs.extract_note(xhs.parse_initial_state(page(MOBILE_STATE)), NOTE_ID, TOKEN)
        self.assertEqual((note.title, note.author, note.author_id, note.likes, note.shares),
                         ("中科大读博礼物", "飞翔的托妞", "646a", "236", "1.3万"))
        self.assertEqual(note.desc, "硕转博成功[笑哭]\n#中科大 #读博日常")
        self.assertEqual(note.tags, ["中科大", "读博日常", "modely"])
        self.assertEqual(note.ip_location, "")
        self.assertEqual([i.url for i in note.images], [
            "https://ci.xiaohongshu.com/1040g2sg326e4atod4a105o6s1fog8pk1gafanh0?imageView2/format/jpeg",
            "https://ci.xiaohongshu.com/spectrum/1040g0k0aaa?imageView2/format/jpeg"])
        self.assertTrue(note.images[0].fallback.startswith("https://sns-webpic-qc.xhscdn.com/"))
        self.assertEqual(note.images[1].live_video, "http://sns-video-v3.xhscdn.com/live.mp4")
        self.assertEqual(note.video_url, "")
        self.assertEqual(note.url, f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}?xsec_token=CBnUvZ3vM8Dr%3D"
                                   "&xsec_source=app_share")
        card = note.card()
        self.assertTrue(card.startswith("【小红书】中科大读博礼物\n作者 飞翔的托妞 · "))
        self.assertIn("赞 236 · 藏 26 · 评 78 · 转 1.3万", card)
        self.assertIn("\n#modely\n", card)  # tags missing from the body are appended once

    def test_desktop_video_note(self):
        note = xhs.extract_note(DESKTOP_STATE, "6ad42e1f0000000031006d38")
        self.assertEqual((note.type, note.author, note.ip_location, note.xsec_token), ("video", "橙柿互动", "浙江", "TOK"))
        self.assertEqual(note.heading, "第一行标题")
        self.assertEqual(note.tags, ["法国"])
        self.assertEqual(note.video_url, "https://sns-video-bd.xhscdn.com/spectrum/origin")
        self.assertEqual(note.video_fallbacks, ["https://sns-video-v3.xhscdn.com/h264.mp4",
                                                "https://sns-bak-v1.xhscdn.com/h264.mp4"])
        self.assertEqual(note.images[0].url, "https://ci.xiaohongshu.com/110/0/01e50c1c?imageView2/format/jpeg")
        self.assertIn("视频：https://sns-video-bd.xhscdn.com/spectrum/origin", note.card())

    def test_layout_drift_falls_back_to_search(self):
        state = {"somewhere": {"deep": [{"noteId": NOTE_ID, "desc": "正文", "imageList": []}]}}
        self.assertEqual(xhs.extract_note(state, NOTE_ID).desc, "正文")
        self.assertIsNone(xhs.extract_note({"noteData": {"data": {"noteData": {}}}}, NOTE_ID))

    def test_failure_reason(self):
        self.assertEqual(xhs.failure_reason("https://www.xiaohongshu.com/login?redirectPath=x", ""), "needs_login")
        self.assertEqual(xhs.failure_reason("https://www.xiaohongshu.com/404/sec_X", "当前内容仅支持在小红书 APP 内查看"),
                         "app_only")
        self.assertEqual(xhs.failure_reason("https://www.xiaohongshu.com/404?source=/404/sec_X", ""), "blocked")

    def test_forward_caps_images(self):
        note = xhs.extract_note(xhs.parse_initial_state(page(MOBILE_STATE)), NOTE_ID)
        images = [(b"\xff\xd8" + bytes([i]), "image/jpeg") for i in range(3)]
        reply = xhs.build_forward(note, images, total_images=25)
        nodes = reply.actions[0]["nodes"]
        self.assertEqual(reply.actions[0]["type"], "forward")
        self.assertEqual([n["actions"][0]["type"] for n in nodes], ["text", "image", "image", "image", "text"])
        self.assertEqual(nodes[-1]["actions"][0]["text"], "原笔记共 25 张图，这里放了 3 张，完整内容见原链接。")
        self.assertTrue(all(n["name"] == "嘟嘟哒" for n in nodes))


class ObserverTests(unittest.TestCase):
    def setUp(self):
        xhs._recent.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kv = {}
        self.calls = []

    def ctx(self, text, responses, segments=(), config=None):
        async def fetch(url, headers=None, **kwargs):
            self.calls.append((url, (headers or {}).get("User-Agent", ""), (headers or {}).get("Cookie", "")))
            for prefix, response in responses.items():
                if url.startswith(prefix):
                    if isinstance(response, Exception):
                        raise response
                    return response
            raise FeatureError("请求失败（HTTP 404）")

        def state_dir(feature):
            path = Path(self.tmp.name) / feature
            path.mkdir(parents=True, exist_ok=True)
            return path

        message = Inbound(account_id="qq-1", conversation_id="qq-1:group:100", message_id="m", text=text,
                          sender=Sender(id="7"), segments=list(segments))
        return SimpleNamespace(inbound=message, config=lambda name: config or {}, fetch=fetch, state_dir=state_dir,
                               kv_set=lambda feature, key, value: self.kv.__setitem__((feature, key), value))

    def test_short_link_archives_and_forwards(self):
        jpeg = b"\xff\xd8\xff\xe0" + b"1" * 32
        responses = {
            "https://xhslink.com/m/7i4ACv0Q0sS": (page(MOBILE_STATE).encode(), {}, SHARE),
            "https://ci.xiaohongshu.com/1040g2sg": (jpeg, {"content-type": "image/jpeg"}, ""),
            "https://ci.xiaohongshu.com/spectrum/": FeatureError("请求失败（HTTP 403）"),
            "https://sns-webpic-qc.xhscdn.com/": (b"\x89PNG" + b"2" * 16, {"content-type": "image/png"}, ""),
        }
        ctx = self.ctx("口令 xhslink.com/m/7i4ACv0Q0sS 复制后打开【小红书】", responses)
        reply = asyncio.run(xhs.xhs_archive(ctx))
        nodes = reply.actions[0]["nodes"]
        self.assertEqual([n["actions"][0].get("mime") for n in nodes[1:]], ["image/jpeg", "image/png"])
        self.assertTrue(nodes[0]["actions"][0]["text"].startswith("【小红书】中科大读博礼物"))
        self.assertIn(xhs.MOBILE_UA, [ua for _, ua, _ in self.calls])
        folder = Path(self.tmp.name) / "xiaohongshu" / NOTE_ID
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["01.jpg", "02.png", "note.json", "note.md"])
        markdown = (folder / "note.md").read_text()
        self.assertIn("![01.jpg](01.jpg)", markdown)
        self.assertIn("## 实况", markdown)
        self.assertEqual(json.loads((folder / "note.json").read_text())["id"], NOTE_ID)
        self.assertEqual(self.kv[("xiaohongshu", f"note:{NOTE_ID}")]["images"], 2)
        # Same note again (now as a full URL card) within the window: silent.
        self.calls.clear()
        again = self.ctx("[卡片]", responses, segments=[{"type": "light_app", "title": "t", "url": SHARE}])
        self.assertIsNone(asyncio.run(xhs.xhs_archive(again)))
        self.assertEqual(self.calls, [])

    def test_blocked_note_records_error_and_stays_silent(self):
        blocked = ("https://www.xiaohongshu.com/404/sec_X?source=xhs_sec_server&originalUrl=http%3A%2F%2Fwww."
                   f"xiaohongshu.com%2Fdiscovery%2Fitem%2F{NOTE_ID}%3Fxsec_token%3DABC")
        login = "https://www.xiaohongshu.com/login?redirectPath=x"
        responses = {
            "http://xhslink.com/o/old": ("当前内容仅支持在小红书 APP 内查看".encode(), {}, blocked),
            "https://www.xiaohongshu.com/discovery/item/": (b"<html>app only</html>", {}, blocked),
            "https://www.xiaohongshu.com/explore/": (b"<html>login</html>", {}, login),
        }
        ctx = self.ctx("http://xhslink.com/o/old", responses, config={"cookie": "web_session=abc"})
        self.assertIsNone(asyncio.run(xhs.xhs_archive(ctx)))
        error = self.kv[("xiaohongshu", "last_error")]
        self.assertEqual((error["note_id"], error["reason"]), (NOTE_ID, "needs_login"))
        self.assertIn(("xiaohongshu", f"error:{NOTE_ID}"), self.kv)
        self.assertTrue(all(cookie == "web_session=abc" for _, _, cookie in self.calls))
        self.assertEqual({ua for _, ua, _ in self.calls}, {xhs.MOBILE_UA, xhs.USER_AGENT})

    def test_ignores_non_note_links(self):
        ctx = self.ctx("https://www.xiaohongshu.com/user/profile/647c https://www.bilibili.com/video/BV1qYpN6vE7J", {})
        self.assertIsNone(asyncio.run(xhs.xhs_archive(ctx)))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
