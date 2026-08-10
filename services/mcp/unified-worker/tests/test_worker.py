from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from dududa_unified_mcp_worker.worker import Worker


class _FakeHttpClient:
    instances: list[_FakeHttpClient] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.closed = True


class _FakeMcpClient:
    instances: list[_FakeMcpClient] = []

    def __init__(self, transport, **kwargs) -> None:
        self.transport = transport
        self.kwargs = kwargs
        self.protocol_version = "fixture-v2"
        self.closed = False
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.closed = True


class _FailingMcpClient(_FakeMcpClient):
    async def __aenter__(self):
        raise RuntimeError("https-header-secret-sentinel")


class WorkerHttpContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeHttpClient.instances.clear()
        _FakeMcpClient.instances.clear()

    @staticmethod
    def _params() -> dict[str, object]:
        return {
            "transport": "streamable_http",
            "protocol_mode": "auto",
            "endpoint": {
                "url": "https://mcp.example.test/api",
                "headers": {"Authorization": "test-secret"},
            },
            "process_control": None,
            "read_timeout_seconds": 3,
        }

    async def test_https_transport_contract_uses_no_network(self) -> None:
        transport_calls: list[tuple[object, object, object]] = []

        def transport_factory(url, *, http_client, terminate_on_close):
            transport_calls.append((url, http_client, terminate_on_close))
            return object()

        worker = Worker(
            client_factory=_FakeMcpClient,
            http_client_factory=_FakeHttpClient,
            http_transport_factory=transport_factory,
        )
        network_failure = AssertionError("network access is forbidden")
        with (
            patch.object(socket, "create_connection", side_effect=network_failure),
            patch.object(socket, "getaddrinfo", side_effect=network_failure),
        ):
            result = await worker._open(self._params())
            await worker._close_client()

        self.assertEqual(result, {"protocol_version": "fixture-v2"})
        http_client = _FakeHttpClient.instances[0]
        self.assertEqual(
            http_client.kwargs,
            {
                "headers": {"Authorization": "test-secret"},
                "follow_redirects": False,
                "trust_env": False,
            },
        )
        self.assertEqual(
            transport_calls,
            [("https://mcp.example.test/api", http_client, True)],
        )
        self.assertTrue(http_client.closed)
        self.assertTrue(_FakeMcpClient.instances[0].closed)

    async def test_https_failure_response_does_not_expose_url_or_header(self) -> None:
        worker = Worker(
            client_factory=_FailingMcpClient,
            http_client_factory=_FakeHttpClient,
            http_transport_factory=lambda *args, **kwargs: object(),
        )
        responses: list[dict[str, object]] = []

        async def capture(value: dict[str, object]) -> None:
            responses.append(value)

        worker._write = capture
        await worker._execute(
            {
                "v": 1,
                "id": "request-1",
                "method": "open",
                "params": self._params(),
            }
        )
        evidence = repr(responses)
        self.assertNotIn("test-secret", evidence)
        self.assertNotIn("mcp.example.test", evidence)
        self.assertIn("open_operation_failed", evidence)


if __name__ == "__main__":
    unittest.main()
