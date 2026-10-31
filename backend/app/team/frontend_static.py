"""Optional same-origin serving of the built frontend (frontend/dist) by the API process.

Off unless KIROTHON_FRONTEND_DIST points at a built dist folder containing index.html. The existing server
keeps nginx serving /var/www/kirothon-preview and proxying /api, so it does not set this. A new environment
without nginx can run one uvicorn process for both, and the built app's relative /api/... calls need no
Vite dev proxy.

The catch-all route is appended at startup (router lifespan), after every API route including
/api/health in main.py, so it can never shadow an API path. Nothing happens at import time.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ENV_DIST = "KIROTHON_FRONTEND_DIST"
log = logging.getLogger(__name__)


def dist_dir() -> Path | None:
    value = os.environ.get(ENV_DIST, "").strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    return path if (path / "index.html").is_file() else None


def serve(dist: Path, path: str) -> FileResponse:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404)
    if path:
        target = (dist / path).resolve()
        inside = target.is_relative_to(dist)
        if inside and target.is_file() and not any(p.startswith(".") for p in target.relative_to(dist).parts):
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        if path.startswith("assets/") or not inside:
            raise HTTPException(status_code=404)
    # The app keeps its step in the URL hash, so every other path is the single page.
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


def frontend(path: str = ""):
    dist = dist_dir()  # read per request: unset or missing build -> plain 404
    if dist is None:
        raise HTTPException(status_code=404)
    return serve(dist, path)


@asynccontextmanager
async def lifespan(app):
    if dist_dir() is not None and not getattr(app.state, "frontend_route", False):
        app.add_api_route("/{path:path}", frontend, methods=["GET"], include_in_schema=False)
        app.state.frontend_route = True
        log.info("serving built frontend from %s", dist_dir())
    yield


router = APIRouter(lifespan=lifespan)
