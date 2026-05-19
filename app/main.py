import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.quota_fetcher import QuotaFetcher

CLIPROXY_BASE_URL = os.environ.get("CLIPROXY_BASE_URL", "http://localhost:8317")
MANAGEMENT_KEY = os.environ.get("MANAGEMENT_KEY", "")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

app = FastAPI(title="Quota Dashboard", docs_url=None, redoc_url=None)
fetcher = QuotaFetcher(CLIPROXY_BASE_URL, MANAGEMENT_KEY, CACHE_TTL)

STATIC_DIR = Path(__file__).parent / "static"


def _check_auth(request: Request) -> bool:
    if not DASHBOARD_PASSWORD:
        return True
    token = request.headers.get("X-Dashboard-Token", "")
    if token == DASHBOARD_PASSWORD:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == DASHBOARD_PASSWORD:
        return True
    return False


def _index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
async def index():
    return _index()


@app.get("/codex")
async def page_codex():
    return _index()


@app.get("/claude")
async def page_claude():
    return _index()


@app.get("/antigravity")
async def page_antigravity():
    return _index()


@app.get("/gemini-cli")
async def page_gemini_cli():
    return _index()


@app.get("/kimi")
async def page_kimi():
    return _index()


@app.get("/all")
async def page_all():
    return _index()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    password = body.get("password", "")
    if not DASHBOARD_PASSWORD or password == DASHBOARD_PASSWORD:
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)


@app.get("/api/auth-check")
async def auth_check(request: Request):
    if not DASHBOARD_PASSWORD:
        return JSONResponse({"need_auth": False})
    if _check_auth(request):
        return JSONResponse({"need_auth": False})
    return JSONResponse({"need_auth": True})


@app.get("/api/quotas")
async def get_quotas(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "未授权"}, status_code=401)
    data = await fetcher.fetch_all()
    return JSONResponse(data)


@app.post("/api/refresh")
async def refresh_quotas(request: Request, account: str = Query(default="")):
    if not _check_auth(request):
        return JSONResponse({"error": "未授权"}, status_code=401)
    if account:
        result = await fetcher.refresh_account(account)
    else:
        result = await fetcher.refresh_all()
    return JSONResponse(result)


# --- CLIProxyAPI management proxy endpoints ---
# These allow QuotaMenu (native app) to connect via quota-dashboard
# instead of directly to CLIProxyAPI, hiding the management key.

_proxy_headers = {"Authorization": f"Bearer {MANAGEMENT_KEY}"}


@app.get("/v0/management/auth-files")
async def proxy_auth_files(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "未授权"}, status_code=401)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{CLIPROXY_BASE_URL}/v0/management/auth-files",
            headers=_proxy_headers,
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)


@app.post("/v0/management/api-call")
async def proxy_api_call(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "未授权"}, status_code=401)
    body = await request.json()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{CLIPROXY_BASE_URL}/v0/management/api-call",
            json=body,
            headers=_proxy_headers,
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)


@app.get("/v0/management/auth-files/download")
async def proxy_download(request: Request, name: str = Query(...)):
    if not _check_auth(request):
        return JSONResponse({"error": "未授权"}, status_code=401)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{CLIPROXY_BASE_URL}/v0/management/auth-files/download",
            params={"name": name},
            headers=_proxy_headers,
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)
