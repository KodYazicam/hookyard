from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .replay import pretty_json, replay
from .signatures import inspect_headers
from .store import MemoryStore, new_record

STATIC = Path(__file__).parent / "static"
TEMPLATES = Path(__file__).parent / "templates"


class Hub:
    def __init__(self) -> None:
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self.clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app(
    store: MemoryStore | None = None,
    secrets: dict[str, str] | None = None,
) -> FastAPI:
    store = store or MemoryStore()
    secrets = secrets or {}
    hub = Hub()
    app = FastAPI(title="hookyard", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.secrets = secrets
    app.state.hub = hub

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "name": "hookyard"}

    @app.post("/api/bins")
    async def create_bin(payload: dict[str, Any] | None = None) -> dict[str, str]:
        bin_id = (payload or {}).get("id")
        return {"id": store.create_bin(bin_id)}

    @app.get("/api/bins")
    async def list_bins() -> dict[str, list[str]]:
        return {"bins": store.bins()}

    @app.get("/api/bins/{bin_id}")
    async def list_requests(bin_id: str) -> dict[str, Any]:
        return {"bin": bin_id, "requests": [r.to_dict() for r in store.list(bin_id)]}

    @app.delete("/api/bins/{bin_id}")
    async def clear_bin(bin_id: str) -> dict[str, int]:
        return {"cleared": store.clear(bin_id)}

    @app.get("/api/bins/{bin_id}/{request_id}")
    async def get_request(bin_id: str, request_id: str) -> Response:
        record = store.get(bin_id, request_id)
        if not record:
            return JSONResponse({"error": "not found"}, status_code=404)
        data = record.to_dict()
        data["pretty"] = pretty_json(record.body)
        return JSONResponse(data)

    @app.post("/api/bins/{bin_id}/{request_id}/replay")
    async def replay_request(bin_id: str, request_id: str, payload: dict[str, Any]) -> Response:
        record = store.get(bin_id, request_id)
        if not record:
            return JSONResponse({"error": "not found"}, status_code=404)
        target = payload.get("target")
        if not target:
            return JSONResponse({"error": "target required"}, status_code=400)
        return JSONResponse(replay(record, target))

    @app.websocket("/ws")
    async def ws_feed(ws: WebSocket) -> None:
        await hub.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(ws)

    @app.api_route("/b/{bin_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @app.api_route("/b/{bin_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def catch(bin_id: str, request: Request, path: str = "") -> dict[str, Any]:
        store.create_bin(bin_id)
        body = await request.body()
        headers = {k: v for k, v in request.headers.items()}
        signatures = inspect_headers(body, headers, secrets)
        record = new_record(
            bin_id=bin_id,
            method=request.method,
            path="/" + path if path else "/",
            query=str(request.url.query),
            headers=headers,
            body=body.decode("utf-8", errors="replace"),
            remote=request.client.host if request.client else "",
            signatures=signatures,
        )
        store.add(record)
        await hub.broadcast({"type": "request", "record": record.to_dict()})
        # Discord PING compatibility
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                parsed = json.loads(record.body)
                if parsed.get("type") == 1:
                    return {"type": 1}
            except json.JSONDecodeError:
                pass
        return {"ok": True, "id": record.id, "bin": bin_id}

    return app
