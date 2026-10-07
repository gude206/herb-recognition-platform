"""Exercise ASGI upload limits without loading a model or allocating huge images."""
import json
import unittest
from unittest.mock import patch

from starlette.responses import JSONResponse

from api import MAX_UPLOAD_REQUEST_BYTES, app
from upload_limits import BoundedUploadMiddleware


async def invoke(application, chunks, *, headers=(), path="/api/v1/predict", method="POST"):
    """Send distinct ASGI chunks, including requests without Content-Length."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": list(headers), "client": ("127.0.0.1", 12345),
             "server": ("127.0.0.1", 8000), "state": {}}
    messages = []
    reads = 0

    async def receive():
        nonlocal reads
        if reads >= len(chunks):
            return {"type": "http.disconnect"}
        chunk = chunks[reads]
        reads += 1
        return {"type": "http.request", "body": chunk, "more_body": reads < len(chunks)}

    async def send(message):
        messages.append(message)

    await application(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start, body, reads


class UploadBodyLimitTest(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_oversize_is_rejected_before_any_multipart_parse(self):
        chunk = b"x" * (256 * 1024)
        # Reuse the same chunk; never allocate a giant request in memory.
        chunks = [chunk] * 80
        headers = [(b"content-type", b"multipart/form-data; boundary=test"),
                   (b"transfer-encoding", b"chunked"),
                   (b"origin", b"http://127.0.0.1:5173")]
        with patch("starlette.formparsers.MultiPartParser.parse", side_effect=AssertionError("Parser must not start")):
            start, body, reads = await invoke(app, chunks, headers=headers)
        self.assertEqual(start["status"], 413)
        self.assertEqual(reads, MAX_UPLOAD_REQUEST_BYTES // len(chunk) + 1)
        self.assertLess(reads, len(chunks))
        self.assertIn(b"access-control-allow-origin", dict(start["headers"]))
        self.assertIn("10MB", json.loads(body)["detail"])

    async def test_actual_bytes_override_a_false_small_content_length(self):
        async def downstream(*args):
            self.fail("Oversize bodies must not reach the route")

        guard = BoundedUploadMiddleware(downstream, path="/api/v1/predict", max_bytes=8)
        start, _, reads = await invoke(guard, [b"1234", b"56789", b"never read"],
                                      headers=[(b"content-length", b"1")])
        self.assertEqual(start["status"], 413)
        self.assertEqual(reads, 2)

    async def test_declared_oversize_rejects_before_reading_body(self):
        async def downstream(*args):
            self.fail("Oversize bodies must not reach the route")

        guard = BoundedUploadMiddleware(downstream, path="/api/v1/predict", max_bytes=8)
        start, _, reads = await invoke(guard, [b"never read"], headers=[(b"content-length", b"9")])
        self.assertEqual((start["status"], reads), (413, 0))

    async def test_spooled_body_is_replayed_intact_and_closed(self):
        captured = []
        spools = []
        from tempfile import SpooledTemporaryFile

        def make_spool(**kwargs):
            spool = SpooledTemporaryFile(**kwargs)
            spools.append(spool)
            return spool

        async def downstream(scope, receive, send):
            content = bytearray()
            while True:
                message = await receive()
                content.extend(message["body"])
                if not message.get("more_body", False):
                    break
            captured.append(bytes(content))
            self.assertTrue(spools[0]._rolled)
            self.assertEqual((await receive())["type"], "http.disconnect")
            await JSONResponse({"ok": True})(scope, receive, send)

        chunk = b"abcde" * 100_000
        guard = BoundedUploadMiddleware(downstream, path="/api/v1/predict", max_bytes=2_000_000)
        with patch("upload_limits.SpooledTemporaryFile", side_effect=make_spool):
            start, _, reads = await invoke(guard, [chunk] * 3)
        self.assertEqual(start["status"], 200)
        self.assertEqual(reads, 3)
        self.assertEqual(captured, [chunk * 3])
        self.assertTrue(spools[0].closed)

    async def test_other_endpoints_receive_their_original_stream(self):
        first_chunks = []

        async def downstream(scope, receive, send):
            first_chunks.append((await receive())["body"])
            await JSONResponse({"ok": True})(scope, receive, send)

        guard = BoundedUploadMiddleware(downstream, path="/api/v1/predict", max_bytes=1)
        start, _, reads = await invoke(guard, [b"first", b"second"], path="/api/v1/chat")
        self.assertEqual((start["status"], reads, first_chunks), (200, 1, [b"first"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
