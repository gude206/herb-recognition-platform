"""Body bounds apply only to new authentication and administrator routes."""
from starlette.responses import JSONResponse


class AuthBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or scope.get('method') not in {'POST', 'PUT', 'PATCH', 'DELETE'} or not path.startswith(('/api/v1/auth/', '/api/v1/admin/')):
            return await self.app(scope, receive, send)
        maximum = 64 * 1024 if path.startswith('/api/v1/auth/') else (5 * 1024 * 1024 + 64 * 1024 if path.endswith('/cover') else 512 * 1024)
        if path == '/api/v1/auth/me/avatar':
            maximum = 2 * 1024 * 1024 + 64 * 1024
        for name, value in scope.get('headers', []):
            if name.lower() == b'content-length':
                try:
                    length = int(value)
                except ValueError:
                    return await JSONResponse({'detail': '请求长度无效'}, status_code=400)(scope, receive, send)
                if length < 0 or length > maximum:
                    return await JSONResponse({'detail': '认证或文章维护请求过大'}, status_code=413)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > maximum:
                return await JSONResponse({'detail': '认证或文章维护请求过大'}, status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
