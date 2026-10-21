from __future__ import annotations

import argparse
import asyncio
import hmac
import os
import re
import secrets
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response


def create_gateway(
    token: str,
    origin: str,
    upstream_port: int = 2080,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    parsed = urlparse(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not 1024 <= upstream_port <= 65535
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token)
    ):
        raise ValueError("Invalid remote gateway settings")
    client = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{upstream_port}",
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(30, connect=3),
    )
    slots = asyncio.Semaphore(8)
    failures: deque[float] = deque(maxlen=30)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("origin") not in {None, origin}:
            return JSONResponse({"detail": "Origin rejected"}, 403)
        value = request.headers.get("authorization", "")
        if len(value) > 264 or not hmac.compare_digest(value.encode(), f"Bearer {token}".encode()):
            now = monotonic()
            while failures and now - failures[0] >= 60:
                failures.popleft()
            status = 429 if len(failures) >= 30 else 401
            failures.append(now)
            return JSONResponse(
                {"detail": "Access key required"}, status, headers={"Cache-Control": "no-store"}
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Paper-Request"],
        max_age=600,
    )

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "DELETE"])
    async def proxy(path: str, request: Request) -> Response:
        if not re.fullmatch(r"[A-Za-z0-9_&./-]+", path) or any(
            segment in {".", ".."} for segment in path.split("/")
        ):
            return JSONResponse({"detail": "Path rejected"}, 400)
        if request.method != "GET" and request.headers.get("x-paper-request") != "1":
            return JSONResponse({"detail": "Request header required"}, 403)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 65536:
                return JSONResponse({"detail": "Request too large"}, 413)
            body.extend(chunk)
        target = httpx.URL(f"/api/{path}").copy_with(query=request.url.query.encode())
        headers = {
            "Origin": f"http://127.0.0.1:{upstream_port}",
            "X-Paper-Request": "1",
            "Content-Type": "application/json",
        }
        try:
            async with (
                slots,
                client.stream(
                    request.method, target, content=bytes(body), headers=headers
                ) as upstream,
            ):
                payload = bytearray()
                async for chunk in upstream.aiter_bytes():
                    if len(payload) + len(chunk) > 8388608:
                        return JSONResponse({"detail": "Response too large"}, 502)
                    payload.extend(chunk)
                if upstream.is_redirect:
                    return JSONResponse({"detail": "Backend redirect rejected"}, 502)
                return Response(
                    bytes(payload), status_code=upstream.status_code, media_type="application/json"
                )
        except httpx.HTTPError:
            return JSONResponse({"detail": "PC backend unavailable"}, 503)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticated phone gateway for a local backend")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--port", type=int, default=2083)
    parser.add_argument("--upstream-port", type=int, default=2080)
    parser.add_argument("--key-file", type=Path, default=Path(".secrets/phone-access.key"))
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Gateway port must be between 1024 and 65535")
    args.key_file.parent.mkdir(parents=True, exist_ok=True)
    if not args.key_file.exists():
        descriptor = os.open(args.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(32))
    try:
        app = create_gateway(
            args.key_file.read_text(encoding="utf-8").strip(), args.origin, args.upstream_port
        )
    except ValueError:
        parser.error("Invalid gateway configuration; no settings or credentials were printed")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
