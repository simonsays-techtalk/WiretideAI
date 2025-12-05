"""Wiretide FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from fastapi.templating import Jinja2Templates
except Exception:  # pragma: no cover - optional dependency guard
    Jinja2Templates = None
try:
    import jinja2  # type: ignore
except Exception:  # pragma: no cover
    jinja2 = None
try:
    import multipart  # type: ignore

    MULTIPART_AVAILABLE = True
except Exception:  # pragma: no cover
    MULTIPART_AVAILABLE = False
from sqlmodel import Session, select

from .config import get_settings
from .db import get_session, init_db, session_scope
from .routes import router
from .services import ensure_settings_seeded


settings = get_settings()
BASE_PATH = Path(__file__).resolve().parent
STATIC_DIR = (BASE_PATH.parent / settings.static_dir).resolve()
TEMPLATES_DIR = (BASE_PATH.parent / settings.templates_dir).resolve()
templates = (
    Jinja2Templates(directory=str(TEMPLATES_DIR))
    if Jinja2Templates and jinja2 is not None
    else None
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as session:
        ensure_settings_seeded(session)
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    if templates:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "app_name": settings.app_name, "version": settings.version},
    )
    return HTMLResponse(
        content=f"{settings.app_name} v{settings.version}",
        status_code=200,
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Any:
    if not templates:
        return HTMLResponse(content="Templates not available; ensure Jinja2 is installed.", status_code=501)
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/logout")
def logout_admin() -> Any:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(settings.admin_cookie_name)
    return response


if MULTIPART_AVAILABLE:
    @app.post("/login")
    def login_admin(admin_token: str = Form(...)) -> Any:
        if admin_token != settings.admin_token:
            return HTMLResponse(content="Invalid admin token", status_code=401)
        response = RedirectResponse(url="/devices", status_code=303)
        response.set_cookie(
            key=settings.admin_cookie_name,
            value=admin_token,
            httponly=True,
            samesite="lax",
            secure=settings.admin_cookie_secure,
            max_age=60 * 60 * 4,
        )
        return response
else:
    @app.post("/login")
    def login_admin_missing() -> Any:
        return HTMLResponse(
            content="Form login unavailable; install python-multipart.",
            status_code=501,
        )


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    # Simple connectivity check; no schema assumptions.
    session.exec(select(1))
    return {"status": "ok", "version": settings.version}
