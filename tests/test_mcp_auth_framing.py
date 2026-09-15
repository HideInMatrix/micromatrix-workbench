"""Regression checks for early MCP rejection on persistent HTTP connections."""

import socket
import threading
import unittest
from types import SimpleNamespace

from agent_runtime.server import HTTPTransportMetrics, MCPHandler


class AuthFramingTests(unittest.TestCase):
    def exchange(self, request):
        runtime = SimpleNamespace(
            oauth_service=None,
            auth_token="local-test-only",
            auth_enabled=lambda: True,
        )
        server = SimpleNamespace(
            runtime=runtime, transport_metrics=HTTPTransportMetrics()
        )
        client, origin = socket.socketpair()

        def serve():
            with origin:
                MCPHandler(origin, ("127.0.0.1", 0), server)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            client.settimeout(3)
            client.sendall(request)
            chunks = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            client.close()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())

    def rejected_post(self, headers=b""):
        body = b'{"jsonrpc":"2.0","id":1,"method":"initialize"}'
        return self.exchange(
            b"POST /mcp HTTP/1.1\r\nHost: localhost\r\n"
            + headers
            + b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
            + body
            + b"GET /mcp HTTP/1.1\r\nHost: localhost\r\n"
              b"Connection: close\r\n\r\n"
        )

    def assert_closed_rejection(self, response, status):
        self.assertTrue(response.startswith(b"HTTP/1.1 " + str(status).encode()))
        self.assertIn(b"Connection: close\r\n", response)
        self.assertEqual(response.count(b"HTTP/1.1 "), 1)
        self.assertNotIn(b"Unsupported method", response)

    def test_missing_bearer_closes_unread_body(self):
        response = self.rejected_post()
        self.assert_closed_rejection(response, 401)
        self.assertIn(b"missing_token", response)
        self.assertIn(b"WWW-Authenticate: Bearer", response)

    def test_invalid_bearer_closes_unread_body(self):
        response = self.rejected_post(b"Authorization: Bearer invalid-test\r\n")
        self.assert_closed_rejection(response, 401)
        self.assertIn(b"invalid_token", response)

    def test_forbidden_origin_closes_unread_body(self):
        response = self.rejected_post(b"Origin: https://untrusted.example\r\n")
        self.assert_closed_rejection(response, 403)

    def test_authorized_bodyless_request_can_reuse_connection(self):
        response = self.exchange(
            b"GET /mcp HTTP/1.1\r\nHost: localhost\r\n"
            b"Authorization: Bearer local-test-only\r\n\r\n"
            b"GET /mcp HTTP/1.1\r\nHost: localhost\r\n"
            b"Connection: close\r\n\r\n"
        )
        self.assertTrue(response.startswith(b"HTTP/1.1 405"))
        self.assertIn(b"HTTP/1.1 401", response)


if __name__ == "__main__":
    unittest.main()
