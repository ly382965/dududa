from __future__ import annotations

import ast
import gzip
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

PLUGIN_PARENT = Path(__file__).resolve().parents[1] / "apps" / "astrbot-plugins"
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))

from astrbot_plugin_emoji_kitchen.emoji_kitchen import (
    EmojiKitchenService,
    EmojiKitchenUnavailableError,
    EmojiKitchenUnsupportedError,
    EmojiKitchenUsageError,
    parse_emoji_arguments,
    parse_metadata,
)

METADATA_URL = "https://raw.githubusercontent.com/xsalazar/emoji-kitchen-backend/main/app/metadata.json"
IMAGE_URL = (
    "https://www.gstatic.com/android/keyboard/emojikitchen/20240101/1f600+1f622.png"
)
PNG = b"\x89PNG\r\n\x1a\nfixture-image"


def metadata_payload(image_url: str = IMAGE_URL) -> dict[str, object]:
    return {
        "knownSupportedEmoji": ["1f600", "1f62d", "2764-fe0f"],
        "data": {
            "1f600": {
                "alt": "grinning face",
                "combinations": {
                    "1f62d": [
                        {
                            "gStaticUrl": "https://www.gstatic.com/old.png",
                            "alt": "old",
                            "isLatest": False,
                        },
                        {
                            "gStaticUrl": image_url,
                            "alt": "grinning face + crying face",
                            "isLatest": True,
                        },
                    ]
                },
            },
            "1f62d": {"alt": "crying face", "combinations": {}},
            "2764-fe0f": {"alt": "red heart", "combinations": {}},
        },
    }


class EmojiKitchenServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_is_rejected_before_the_second_request(self) -> None:
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw), transport=httpx.MockTransport(handler)
            )
            with self.assertRaises(EmojiKitchenUnavailableError):
                await service._fetch_bytes(
                    IMAGE_URL,
                    max_bytes=100,
                    allowed_hosts=frozenset({"www.gstatic.com"}),
                )
        self.assertEqual(requests, [IMAGE_URL])

    async def test_gzip_expansion_is_bounded(self) -> None:
        class RawStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield gzip.compress(b"x" * 1000)

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw),
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, stream=RawStream(), headers={"content-encoding": "gzip"}
                    )
                ),
            )
            with (
                patch(
                    "gzip.decompress",
                    side_effect=AssertionError("unbounded decompression"),
                ),
                self.assertRaises(EmojiKitchenUnavailableError),
            ):
                await service._fetch_bytes(
                    METADATA_URL,
                    max_bytes=100,
                    allowed_hosts=frozenset({"raw.githubusercontent.com"}),
                    read_compressed=True,
                )

    async def test_resolves_latest_combination_and_reuses_disk_cache(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            if str(request.url) == METADATA_URL:
                return httpx.Response(200, json=metadata_payload())
            if str(request.url) == IMAGE_URL:
                return httpx.Response(
                    200, content=PNG, headers={"content-type": "image/png"}
                )
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = EmojiKitchenService(
                root,
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(handler),
            )
            result = await service.compose("😀 😭")

            self.assertEqual(result.left_codepoint, "1f600")
            self.assertEqual(result.right_codepoint, "1f62d")
            self.assertEqual(result.alt, "grinning face + crying face")
            self.assertEqual(result.image_bytes, PNG)
            self.assertEqual(requests, [METADATA_URL, IMAGE_URL])
            self.assertFalse(
                service.metadata_path.read_bytes().startswith(b"\xef\xbb\xbf")
            )

            def unexpected(request: httpx.Request) -> httpx.Response:
                raise AssertionError(f"cache miss: {request.url}")

            cached_service = EmojiKitchenService(
                root,
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(unexpected),
            )
            cached = await cached_service.compose("😀 😭")
            self.assertEqual(cached.image_bytes, PNG)

    async def test_accepts_variation_selector_alias_and_reverse_pair(self) -> None:
        payload = metadata_payload()
        payload["data"]["2764-fe0f"] = {
            "alt": "red heart",
            "combinations": {
                "1f600": [
                    {
                        "gStaticUrl": IMAGE_URL,
                        "alt": "heart + grinning face",
                        "isLatest": True,
                    }
                ]
            },
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == METADATA_URL:
                return httpx.Response(200, json=payload)
            return httpx.Response(200, content=PNG)

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw),
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(handler),
            )
            result = await service.compose("❤ 😀")
            self.assertEqual(result.left_codepoint, "2764-fe0f")
            self.assertEqual(result.right_codepoint, "1f600")
            self.assertEqual(result.alt, "heart + grinning face")

    async def test_stale_metadata_falls_back_when_refresh_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initial = EmojiKitchenService(
                root,
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(
                    lambda request: (
                        httpx.Response(200, json=metadata_payload())
                        if str(request.url) == METADATA_URL
                        else httpx.Response(200, content=PNG)
                    )
                ),
            )
            await initial.compose("😀 😭")
            os.utime(initial.metadata_path, (0, 0))

            def offline(request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("offline", request=request)

            service = EmojiKitchenService(
                root,
                metadata_ttl_seconds=60,
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(offline),
                clock=lambda: 1_000,
            )
            result = await service.compose("😀 😭")
            self.assertEqual(result.image_bytes, PNG)

    async def test_no_cache_and_remote_failure_is_unavailable(self) -> None:
        def offline(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw),
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(offline),
            )
            with self.assertRaises(EmojiKitchenUnavailableError):
                await service.compose("😀 😭")

    async def test_unsupported_pair_does_not_download_an_image(self) -> None:
        image_requests = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal image_requests
            if str(request.url) == IMAGE_URL:
                image_requests += 1
            return httpx.Response(200, json=metadata_payload())

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw),
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(EmojiKitchenUnsupportedError):
                await service.compose("😀 ❤️")
            self.assertEqual(image_requests, 0)

    async def test_untrusted_image_url_is_rejected(self) -> None:
        payload = metadata_payload("https://example.com/result.png")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw),
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(EmojiKitchenUnavailableError):
                await service.compose("😀 😭")

    async def test_oversized_or_non_png_image_is_rejected(self) -> None:
        payload = metadata_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == METADATA_URL:
                return httpx.Response(200, json=payload)
            return httpx.Response(200, content=b"not-a-png")

        with tempfile.TemporaryDirectory() as raw:
            service = EmojiKitchenService(
                Path(raw),
                metadata_url=METADATA_URL,
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(EmojiKitchenUnavailableError):
                await service.compose("😀 😭")

    def test_argument_and_metadata_validation(self) -> None:
        self.assertEqual(parse_emoji_arguments("  😀\n😭 "), ("😀", "😭"))
        with self.assertRaises(EmojiKitchenUsageError):
            parse_emoji_arguments("😀")
        with self.assertRaises(EmojiKitchenUsageError):
            parse_emoji_arguments("😀 😭 😡")
        parsed = parse_metadata(metadata_payload())
        self.assertEqual(parsed.token_to_codepoint["😀"], "1f600")
        self.assertEqual(parsed.token_to_codepoint["❤"], "2764-fe0f")

    def test_proxy_prefers_explicit_http_proxy_and_ignores_socks_only_proxy(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "DUDUDA_EMOJI_KITCHEN_HTTP_PROXY": "http://proxy.example:7890",
                "HTTPS_PROXY": "socks5://proxy.example:7891",
                "https_proxy": "",
                "HTTP_PROXY": "",
                "http_proxy": "",
            },
            clear=True,
        ):
            self.assertEqual(
                EmojiKitchenService._http_proxy(), "http://proxy.example:7890"
            )
        with patch.dict(
            os.environ,
            {"DUDUDA_EMOJI_KITCHEN_HTTP_PROXY": "socks5://proxy.example:7890"},
            clear=True,
        ):
            self.assertIsNone(EmojiKitchenService._http_proxy())

    def test_plugin_entry_is_standalone_and_exposes_the_command(self) -> None:
        plugin_root = PLUGIN_PARENT / "astrbot_plugin_emoji_kitchen"
        source = (plugin_root / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("astrbot_plugin_dududa_core", source)
        tree = ast.parse(source)
        registration = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "register"
        )
        self.assertEqual(
            ast.unparse(registration),
            "register('astrbot_plugin_emoji_kitchen', 'mmdustc', '基于 Google Emoji Kitchen 的官方表情合成', '1.0.0')",
        )
        command = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "emoji"
        )
        self.assertEqual(
            ast.unparse(command.decorator_list[0]),
            "filter.command('emoji', alias={'表情合成'})",
        )


if __name__ == "__main__":
    unittest.main()
