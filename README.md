# CLIProxyAPI-QuotaDashboard

A web dashboard for monitoring AI provider quota usage, powered by [CLIProxyAPI](https://github.com/nicepkg/CLIProxyAPI).

## Features

- **Multi-provider support** — Claude, Codex, Antigravity (Cloud Code), Gemini CLI, Kimi
- **Real-time quota display** — usage percentage, progress bars, reset time
- **Per-account refresh** — refresh individual accounts
- **Password protection** — optional dashboard password
- **Management API proxy** — allows [QuotaMenu](https://github.com/xuan-wei/CLIProxyAPI-QuotaMenu) (native macOS app) to connect without exposing the CLIProxyAPI management key

## Quick Start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
CLIPROXY_BASE_URL=https://your-cliproxyapi-instance.com
MANAGEMENT_KEY=your-management-key
CACHE_TTL=60
DASHBOARD_PASSWORD=your-dashboard-password
```

| Variable | Description | Default |
|---|---|---|
| `CLIPROXY_BASE_URL` | CLIProxyAPI instance URL | `http://localhost:8317` |
| `MANAGEMENT_KEY` | CLIProxyAPI management key | (required) |
| `CACHE_TTL` | Cache duration in seconds | `300` |
| `DASHBOARD_PASSWORD` | Dashboard login password (empty = no auth) | (empty) |

### 2. Deploy with Docker

```bash
docker compose up -d --build
```

The dashboard will be available at `http://localhost:8318`.

### 3. Run locally (development)

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8318
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard web UI |
| `GET /api/quotas` | Fetch all quota data |
| `POST /api/refresh` | Refresh all or single account (`?account=name`) |
| `POST /api/login` | Authenticate with dashboard password |
| `GET /api/auth-check` | Check if authentication is required |

### Management API Proxy

These endpoints proxy CLIProxyAPI management API, authenticated with the dashboard password instead of the management key:

| Endpoint | Proxies to |
|---|---|
| `GET /v0/management/auth-files` | CLIProxyAPI auth file listing |
| `POST /v0/management/api-call` | CLIProxyAPI API call proxy |
| `GET /v0/management/auth-files/download` | CLIProxyAPI auth file download |

## License

MIT

## Contributors

- **Xuan Wei** ([@xuan-wei](https://github.com/xuan-wei))
- **Claude** by [Anthropic](https://www.anthropic.com)
