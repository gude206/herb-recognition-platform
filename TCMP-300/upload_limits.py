"""Bound image uploads before FastAPI starts parsing multipart files."""
from tempfile import SpooledTemporaryFile

import anyio
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BoundedUploadMiddleware:
    """Buffer a bounded body, then replay it without keeping a large RAM copy.

    Content-Length is only an early rejection hint. Counting received bytes also
    protects chunked requests and incorrect/missing length headers. Multipart
    parsing never begins for bodies over the limit. Disk I/O uses the thread pool.
    """

    def __init__(self, app: ASGIApp, *, path: str, max_bytes: int):
        self.app = app
        self.path = path
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or scope["path"] != self.path):
            await self.app(scope, receive, send)
            return

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                length = int(value)
                if length < 0:
                    raise ValueError()
            except ValueError:
                await reject(400, "上传请求长度无效")
                return
            if length > self.max_bytes:
                await reject(413, "上传请求过大，图片不能超过 10MB")
                return

        body = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        try:
            received = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > self.max_bytes:
                    await reject(413, "上传请求过大，图片不能超过 10MB")
                    return
                if chunk:
                    await run_in_threadpool(body.write, chunk)
                if not message.get("more_body", False):
                    break

            await run_in_threadpool(body.seek, 0)
            remaining = received
            empty_replayed = False

            async def replay():
                nonlocal remaining, empty_replayed
                if remaining:
                    chunk = await run_in_threadpool(body.read, min(64 * 1024, remaining))
                    remaining -= len(chunk)
                    return {"type": "http.request", "body": chunk, "more_body": remaining > 0}
                # Once the saved request has been replayed, keep disconnect and
                # response cancellation semantics tied to the original receive.
                if received == 0 and not empty_replayed:
                    empty_replayed = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            # A cancelled connection must also release its temporary file.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(body.close)


class SingleImageUploadRoute(APIRoute):
    """Apply multipart cardinality limits before File(...) dependencies run."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            # Starlette closes partially created files when these limits fail.
            form = await request.form(max_files=1, max_fields=0)
            try:
                if any(name != "file" for name, _ in form.multi_items()):
                    raise HTTPException(422, "请只上传一个名为 file 的图片文件")
                return await original(request)
            finally:
                await form.close()

        return handler
