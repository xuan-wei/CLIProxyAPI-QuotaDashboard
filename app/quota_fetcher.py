import asyncio
import json
import time
from datetime import datetime, timezone

import httpx

CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_REQUEST_HEADERS = {
    "Authorization": "Bearer $TOKEN$",
    "Content-Type": "application/json",
    "User-Agent": "codex_cli_rs/0.76.0 (Debian 13.0.0; x86_64) WindowsTerminal",
}

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
CLAUDE_REQUEST_HEADERS = {
    "Authorization": "Bearer $TOKEN$",
    "Content-Type": "application/json",
    "anthropic-beta": "oauth-2025-04-20",
}

CLAUDE_USAGE_WINDOW_KEYS = [
    ("five_hour", "5小时窗口"),
    ("seven_day", "7天窗口"),
    ("seven_day_oauth_apps", "7天 OAuth Apps"),
    ("seven_day_opus", "7天 Opus"),
    ("seven_day_sonnet", "7天 Sonnet"),
    ("seven_day_cowork", "7天 Cowork"),
    ("iguana_necktie", "Iguana Necktie"),
]

ANTIGRAVITY_QUOTA_URLS = [
    "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
    "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:fetchAvailableModels",
    "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
]
ANTIGRAVITY_REQUEST_HEADERS = {
    "Authorization": "Bearer $TOKEN$",
    "Content-Type": "application/json",
    "User-Agent": "antigravity/1.11.5 windows/amd64",
}
ANTIGRAVITY_QUOTA_GROUPS = [
    {"id": "claude-gpt", "label": "Claude/GPT", "identifiers": ["claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium"]},
    {"id": "gemini-3-pro", "label": "Gemini 3 Pro", "identifiers": ["gemini-3-pro-high", "gemini-3-pro-low"]},
    {"id": "gemini-3-1-pro-series", "label": "Gemini 3.1 Pro Series", "identifiers": ["gemini-3.1-pro-high", "gemini-3.1-pro-low"]},
    {"id": "gemini-2-5-flash", "label": "Gemini 2.5 Flash", "identifiers": ["gemini-2.5-flash", "gemini-2.5-flash-thinking"]},
    {"id": "gemini-2-5-flash-lite", "label": "Gemini 2.5 Flash Lite", "identifiers": ["gemini-2.5-flash-lite"]},
    {"id": "gemini-2-5-cu", "label": "Gemini 2.5 CU", "identifiers": ["rev19-uic3-1p"]},
    {"id": "gemini-3-flash", "label": "Gemini 3 Flash", "identifiers": ["gemini-3-flash"]},
    {"id": "gemini-image", "label": "gemini-3.1-flash-image", "identifiers": ["gemini-3.1-flash-image"]},
]

GEMINI_CLI_QUOTA_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
GEMINI_CLI_CODE_ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
GEMINI_CLI_REQUEST_HEADERS = {
    "Authorization": "Bearer $TOKEN$",
    "Content-Type": "application/json",
}
GEMINI_CLI_QUOTA_GROUPS = [
    {"id": "gemini-flash-lite-series", "label": "Gemini Flash Lite Series", "model_ids": ["gemini-2.5-flash-lite"]},
    {"id": "gemini-flash-series", "label": "Gemini Flash Series", "model_ids": ["gemini-3-flash-preview", "gemini-2.5-flash"]},
    {"id": "gemini-pro-series", "label": "Gemini Pro Series", "model_ids": ["gemini-3.1-pro-preview", "gemini-3-pro-preview", "gemini-2.5-pro"]},
]

KIMI_USAGE_URL = "https://api.kimi.com/coding/v1/usages"
KIMI_REQUEST_HEADERS = {
    "Authorization": "Bearer $TOKEN$",
}

DEFAULT_ANTIGRAVITY_PROJECT_ID = "bamboo-precept-lgxtn"


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _parse_json_or_obj(data):
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        data = data.strip()
        if not data:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value if not (isinstance(value, float) and (value != value)) else None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return float(value) if "." in value else int(value)
        except (ValueError, TypeError):
            return None
    return None


def _format_reset_time(value):
    if value is None:
        return None
    n = _num(value)
    if n is not None and n > 0:
        if n < 1e12:
            n = n * 1000
        try:
            dt = datetime.fromtimestamp(n / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _format_unix_seconds(ts):
    n = _num(ts)
    if n is None or n <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(n, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OSError, ValueError):
        return None


class QuotaFetcher:
    def __init__(self, base_url: str, management_key: str, cache_ttl: int = 300):
        self.base_url = base_url.rstrip("/")
        self.management_key = management_key
        self.cache_ttl = cache_ttl
        self._account_cache: dict[str, dict] = {}
        self._account_times: dict[str, float] = {}
        self._files_cache: list[dict] | None = None
        self._files_cache_time: float = 0

    async def _api_call(self, client: httpx.AsyncClient, auth_index: str, method: str, url: str,
                        headers: dict, data: str | None = None) -> dict:
        payload = {
            "authIndex": auth_index,
            "method": method,
            "url": url,
            "header": headers,
        }
        if data is not None:
            payload["data"] = data

        resp = await client.post(
            f"{self.base_url}/v0/management/api-call",
            json=payload,
            headers={"Authorization": f"Bearer {self.management_key}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    async def _get_auth_files(self, client: httpx.AsyncClient) -> list[dict]:
        resp = await client.get(
            f"{self.base_url}/v0/management/auth-files",
            headers={"Authorization": f"Bearer {self.management_key}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("files", [])

    async def _download_auth_file_text(self, client: httpx.AsyncClient, name: str) -> str | None:
        try:
            resp = await client.get(
                f"{self.base_url}/v0/management/auth-files/download",
                params={"name": name},
                headers={"Authorization": f"Bearer {self.management_key}"},
                timeout=15.0,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None

    def _resolve_provider(self, f: dict) -> str | None:
        for key in ("provider", "type"):
            val = f.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
        name = f.get("name", "")
        if isinstance(name, str):
            nl = name.lower()
            if nl.startswith("codex-"):
                return "codex"
            if nl.startswith("claude-"):
                return "claude"
            if "antigravity" in nl or "cloudcode" in nl:
                return "antigravity"
            if "gemini" in nl:
                return "gemini-cli"
            if "kimi" in nl:
                return "kimi"
        return None

    def _is_disabled(self, f: dict) -> bool:
        d = f.get("disabled")
        if isinstance(d, bool):
            return d
        if isinstance(d, (int, float)):
            return bool(d)
        if isinstance(d, str):
            return d.strip().lower() in ("true", "1", "yes")
        return False

    async def _fetch_codex_quota(self, client: httpx.AsyncClient, f: dict) -> dict:
        auth_index = f.get("auth_index") or f.get("authIndex", "")
        id_token = f.get("id_token") or {}
        if isinstance(id_token, str):
            id_token = _parse_json_or_obj(id_token) or {}

        account_id = id_token.get("chatgpt_account_id") or id_token.get("chatgptAccountId")
        plan_type_fallback = id_token.get("plan_type") or id_token.get("planType")

        headers = dict(CODEX_REQUEST_HEADERS)
        if account_id:
            headers["Chatgpt-Account-Id"] = str(account_id)

        try:
            result = await self._api_call(client, auth_index, "GET", CODEX_USAGE_URL, headers)
        except Exception as e:
            return self._error_result("codex", f, str(e))

        status_code = result.get("status_code", 0)
        if status_code < 200 or status_code >= 300:
            return self._error_result("codex", f, f"HTTP {status_code}")

        body = _parse_json_or_obj(result.get("body") or result.get("bodyText"))
        if not body:
            return self._error_result("codex", f, "Empty response")

        plan_type = body.get("plan_type") or body.get("planType") or plan_type_fallback
        windows = []

        rate_limit = body.get("rate_limit") or body.get("rateLimit") or {}
        for window_key, label in [("primary_window", "5小时窗口"), ("secondary_window", "7天窗口")]:
            w = rate_limit.get(window_key) or rate_limit.get(
                window_key.replace("_w", "W").replace("_window", "Window")
            )
            if not w:
                continue
            limit_secs = _num(_first(w.get("limit_window_seconds"), w.get("limitWindowSeconds")))
            if limit_secs == 604800:
                label = "7天窗口"
            elif limit_secs == 18000:
                label = "5小时窗口"

            used_pct = _num(_first(w.get("used_percent"), w.get("usedPercent")))
            reset_at = _num(_first(w.get("reset_at"), w.get("resetAt")))
            reset_label = _format_unix_seconds(reset_at) if reset_at else None

            if reset_label is None:
                reset_after = _num(_first(w.get("reset_after_seconds"), w.get("resetAfterSeconds")))
                if reset_after and reset_after > 0:
                    target = int(time.time() + reset_after)
                    reset_label = _format_unix_seconds(target)

            windows.append({
                "label": label,
                "used_percent": used_pct,
                "remaining_percent": max(0, min(100, 100 - used_pct)) if used_pct is not None else None,
                "reset_at": reset_label,
            })

        additional = body.get("additional_rate_limits") or body.get("additionalRateLimits") or []
        for item in additional:
            name = item.get("limit_name") or item.get("limitName") or item.get("metered_feature") or item.get("meteredFeature") or "Additional"
            rl = item.get("rate_limit") or item.get("rateLimit") or {}
            for wk, wl in [("primary_window", f"{name} 5小时"), ("secondary_window", f"{name} 7天")]:
                w = rl.get(wk) or rl.get(wk.replace("_w", "W").replace("_window", "Window"))
                if not w:
                    continue
                used_pct = _num(_first(w.get("used_percent"), w.get("usedPercent")))
                reset_at = _num(_first(w.get("reset_at"), w.get("resetAt")))
                reset_label = _format_unix_seconds(reset_at) if reset_at else None
                if reset_label is None:
                    reset_after = _num(_first(w.get("reset_after_seconds"), w.get("resetAfterSeconds")))
                    if reset_after and reset_after > 0:
                        reset_label = _format_unix_seconds(int(time.time() + reset_after))
                windows.append({
                    "label": wl,
                    "used_percent": used_pct,
                    "remaining_percent": max(0, min(100, 100 - used_pct)) if used_pct is not None else None,
                    "reset_at": reset_label,
                })

        return {
            "provider": "codex",
            "account": f.get("account") or f.get("email") or f.get("label") or f.get("name", ""),
            "plan": plan_type,
            "disabled": self._is_disabled(f),
            "status": "success",
            "windows": windows,
        }

    async def _fetch_claude_quota(self, client: httpx.AsyncClient, f: dict) -> dict:
        auth_index = f.get("auth_index") or f.get("authIndex", "")
        headers = dict(CLAUDE_REQUEST_HEADERS)

        try:
            usage_result, profile_result = await asyncio.gather(
                self._api_call(client, auth_index, "GET", CLAUDE_USAGE_URL, headers),
                self._api_call(client, auth_index, "GET", CLAUDE_PROFILE_URL, headers),
                return_exceptions=True,
            )
        except Exception as e:
            return self._error_result("claude", f, str(e))

        if isinstance(usage_result, Exception):
            return self._error_result("claude", f, str(usage_result))

        status_code = usage_result.get("status_code", 0)
        if status_code < 200 or status_code >= 300:
            return self._error_result("claude", f, f"HTTP {status_code}")

        usage_body = _parse_json_or_obj(usage_result.get("body") or usage_result.get("bodyText"))
        if not usage_body:
            return self._error_result("claude", f, "Empty usage response")

        windows = []
        for key, label in CLAUDE_USAGE_WINDOW_KEYS:
            w = usage_body.get(key)
            if not w or not isinstance(w, dict):
                continue
            utilization = _num(w.get("utilization"))
            if utilization is None:
                continue
            used_pct = utilization
            reset_label = _format_reset_time(w.get("resets_at"))
            windows.append({
                "label": label,
                "used_percent": round(used_pct, 1),
                "remaining_percent": round(max(0, min(100, 100 - used_pct)), 1),
                "reset_at": reset_label,
            })

        plan_type = None
        profile_body = None
        if not isinstance(profile_result, Exception):
            psc = profile_result.get("status_code", 0)
            if 200 <= psc < 300:
                profile_body = _parse_json_or_obj(profile_result.get("body") or profile_result.get("bodyText"))

        if profile_body:
            account = profile_body.get("account") or {}
            org = profile_body.get("organization") or {}
            if account.get("has_claude_max"):
                plan_type = "Max"
            elif account.get("has_claude_pro"):
                plan_type = "Pro"
            elif org.get("organization_type") == "claude_team" and org.get("subscription_status") == "active":
                plan_type = "Team"
            elif account.get("has_claude_max") is False and account.get("has_claude_pro") is False:
                plan_type = "Free"

        extra_usage = usage_body.get("extra_usage")
        extra = None
        if extra_usage and isinstance(extra_usage, dict) and extra_usage.get("is_enabled"):
            used_credits = _num(extra_usage.get("used_credits")) or 0
            monthly_limit = _num(extra_usage.get("monthly_limit")) or 0
            extra = {
                "label": "额外用量",
                "used": f"${used_credits / 100:.2f}",
                "limit": f"${monthly_limit / 100:.2f}",
            }

        return {
            "provider": "claude",
            "account": f.get("account") or f.get("email") or f.get("label") or f.get("name", ""),
            "plan": plan_type,
            "disabled": self._is_disabled(f),
            "status": "success",
            "windows": windows,
            "extra": extra,
        }

    async def _fetch_antigravity_quota(self, client: httpx.AsyncClient, f: dict) -> dict:
        auth_index = f.get("auth_index") or f.get("authIndex", "")
        headers = dict(ANTIGRAVITY_REQUEST_HEADERS)

        project_id = DEFAULT_ANTIGRAVITY_PROJECT_ID
        text = await self._download_auth_file_text(client, f.get("name", ""))
        if text:
            parsed = _parse_json_or_obj(text)
            if parsed:
                project_id = (
                    parsed.get("project_id") or parsed.get("projectId")
                    or (parsed.get("installed") or {}).get("project_id")
                    or (parsed.get("installed") or {}).get("projectId")
                    or (parsed.get("web") or {}).get("project_id")
                    or (parsed.get("web") or {}).get("projectId")
                    or project_id
                )

        last_error = None
        for url in ANTIGRAVITY_QUOTA_URLS:
            try:
                result = await self._api_call(
                    client, auth_index, "POST", url, headers,
                    data=json.dumps({"project": project_id}),
                )
            except Exception as e:
                last_error = str(e)
                continue

            sc = result.get("status_code", 0)
            if sc < 200 or sc >= 300:
                last_error = f"HTTP {sc}"
                continue

            body = _parse_json_or_obj(result.get("body") or result.get("bodyText"))
            if not body:
                if isinstance(result.get("body"), str):
                    body = _parse_json_or_obj(result["body"])
            if body and "models" not in body:
                nested = _parse_json_or_obj(body.get("body"))
                if nested:
                    body = nested

            models = body.get("models") if body else None
            if not models or not isinstance(models, dict):
                last_error = "Empty models"
                continue

            groups = []
            for gdef in ANTIGRAVITY_QUOTA_GROUPS:
                min_fraction = None
                reset_time = None
                matched = False
                for ident in gdef["identifiers"]:
                    model = models.get(ident)
                    if not model:
                        for mk, mv in models.items():
                            dn = (mv.get("displayName") or "") if isinstance(mv, dict) else ""
                            if dn.lower() == ident.lower() or mk.lower() == ident.lower():
                                model = mv
                                break
                    if not model or not isinstance(model, dict):
                        continue
                    qi = model.get("quotaInfo") or model.get("quota_info") or {}
                    frac = _num(_first(qi.get("remainingFraction"), qi.get("remaining_fraction"), qi.get("remaining")))
                    rt = qi.get("resetTime") or qi.get("reset_time")
                    if frac is not None:
                        matched = True
                        if min_fraction is None or frac < min_fraction:
                            min_fraction = frac
                    if rt and not reset_time:
                        reset_time = rt
                        if frac is None:
                            matched = True
                            min_fraction = 0

                if matched:
                    remaining_pct = round(min_fraction * 100, 1) if min_fraction is not None else 0
                    groups.append({
                        "label": gdef["label"],
                        "used_percent": round(100 - remaining_pct, 1),
                        "remaining_percent": remaining_pct,
                        "reset_at": _format_reset_time(reset_time),
                    })

            return {
                "provider": "antigravity",
                "account": f.get("account") or f.get("email") or f.get("label") or f.get("name", ""),
                "plan": "Cloud Code",
                "disabled": self._is_disabled(f),
                "status": "success",
                "windows": groups,
            }

        return self._error_result("antigravity", f, last_error or "All URLs failed")

    async def _fetch_gemini_cli_quota(self, client: httpx.AsyncClient, f: dict) -> dict:
        auth_index = f.get("auth_index") or f.get("authIndex", "")
        headers = dict(GEMINI_CLI_REQUEST_HEADERS)

        project_id = None
        text = await self._download_auth_file_text(client, f.get("name", ""))
        if text:
            parsed = _parse_json_or_obj(text)
            if parsed:
                project_id = (
                    parsed.get("project_id") or parsed.get("projectId")
                    or (parsed.get("installed") or {}).get("project_id")
                    or (parsed.get("installed") or {}).get("projectId")
                )
        if not project_id:
            return self._error_result("gemini-cli", f, "Missing project ID")

        try:
            result = await self._api_call(
                client, auth_index, "POST", GEMINI_CLI_QUOTA_URL, headers,
                data=json.dumps({"project": project_id}),
            )
        except Exception as e:
            return self._error_result("gemini-cli", f, str(e))

        sc = result.get("status_code", 0)
        if sc < 200 or sc >= 300:
            return self._error_result("gemini-cli", f, f"HTTP {sc}")

        body = _parse_json_or_obj(result.get("body") or result.get("bodyText"))
        if not body:
            return self._error_result("gemini-cli", f, "Empty response")

        raw_buckets = body.get("buckets") or []
        parsed_buckets = {}
        for b in raw_buckets:
            model_id = b.get("modelId") or b.get("model_id") or ""
            if isinstance(model_id, str) and model_id.endswith("_vertex"):
                model_id = model_id[:-7]
            if not model_id:
                continue
            frac = _num(_first(b.get("remainingFraction"), b.get("remaining_fraction")))
            amount = _num(_first(b.get("remainingAmount"), b.get("remaining_amount")))
            rt = b.get("resetTime") or b.get("reset_time")
            if frac is None:
                if amount is not None and amount <= 0:
                    frac = 0.0
                elif rt:
                    frac = 0.0
            parsed_buckets[model_id] = {
                "remainingFraction": frac,
                "remainingAmount": amount,
                "resetTime": rt,
            }

        windows = []
        for gdef in GEMINI_CLI_QUOTA_GROUPS:
            min_frac = None
            reset_time = None
            for mid in gdef["model_ids"]:
                bkt = parsed_buckets.get(mid)
                if not bkt:
                    continue
                f_val = bkt["remainingFraction"]
                if f_val is not None:
                    if min_frac is None or f_val < min_frac:
                        min_frac = f_val
                if bkt["resetTime"] and not reset_time:
                    reset_time = bkt["resetTime"]
            if min_frac is not None:
                remaining_pct = round(min_frac * 100, 1)
                windows.append({
                    "label": gdef["label"],
                    "used_percent": round(100 - remaining_pct, 1),
                    "remaining_percent": remaining_pct,
                    "reset_at": _format_reset_time(reset_time),
                })

        tier_label = None
        try:
            ca_result = await self._api_call(
                client, auth_index, "POST", GEMINI_CLI_CODE_ASSIST_URL, headers,
                data=json.dumps({"project": project_id}),
            )
            ca_sc = ca_result.get("status_code", 0)
            if 200 <= ca_sc < 300:
                ca_body = _parse_json_or_obj(ca_result.get("body") or ca_result.get("bodyText"))
                if ca_body:
                    tier = ca_body.get("currentTier") or ca_body.get("current_tier")
                    if tier:
                        tier_label = tier.get("name") or tier.get("id")
        except Exception:
            pass

        return {
            "provider": "gemini-cli",
            "account": f.get("account") or f.get("email") or f.get("label") or f.get("name", ""),
            "plan": tier_label or "Gemini CLI",
            "disabled": self._is_disabled(f),
            "status": "success",
            "windows": windows,
        }

    async def _fetch_kimi_quota(self, client: httpx.AsyncClient, f: dict) -> dict:
        auth_index = f.get("auth_index") or f.get("authIndex", "")
        headers = dict(KIMI_REQUEST_HEADERS)

        try:
            result = await self._api_call(client, auth_index, "GET", KIMI_USAGE_URL, headers)
        except Exception as e:
            return self._error_result("kimi", f, str(e))

        sc = result.get("status_code", 0)
        if sc < 200 or sc >= 300:
            return self._error_result("kimi", f, f"HTTP {sc}")

        body = _parse_json_or_obj(result.get("body") or result.get("bodyText"))
        if not body:
            return self._error_result("kimi", f, "Empty response")

        rows = []
        limits = body.get("limits") or []
        for item in limits:
            name = item.get("title") or item.get("name") or "Limit"
            detail = item.get("detail") or item
            used = _num(detail.get("used")) or 0
            limit = _num(detail.get("limit")) or 0
            remaining = _num(detail.get("remaining"))

            reset_hint = None
            rt = detail.get("resetAt") or detail.get("reset_at") or detail.get("resetTime") or detail.get("reset_time")
            if rt:
                reset_hint = _format_reset_time(rt)
            else:
                ttl = _num(detail.get("ttl") or detail.get("resetIn") or detail.get("reset_in"))
                if ttl and ttl > 0:
                    reset_hint = _format_unix_seconds(int(time.time() + ttl))

            used_pct = round(used / limit * 100, 1) if limit > 0 else (100 if used > 0 else 0)
            remaining_pct = round(max(0, 100 - used_pct), 1)

            rows.append({
                "label": name,
                "used_percent": used_pct,
                "remaining_percent": remaining_pct,
                "reset_at": reset_hint,
                "detail": f"{used}/{limit}" if limit > 0 else str(used),
            })

        if not rows:
            usage = body.get("usage")
            if usage and isinstance(usage, dict):
                used = _num(usage.get("used")) or 0
                limit = _num(usage.get("limit")) or 0
                used_pct = round(used / limit * 100, 1) if limit > 0 else (100 if used > 0 else 0)
                rows.append({
                    "label": "Usage",
                    "used_percent": used_pct,
                    "remaining_percent": round(max(0, 100 - used_pct), 1),
                    "reset_at": None,
                    "detail": f"{used}/{limit}" if limit > 0 else str(used),
                })

        return {
            "provider": "kimi",
            "account": f.get("account") or f.get("email") or f.get("label") or f.get("name", ""),
            "plan": "Kimi",
            "disabled": self._is_disabled(f),
            "status": "success",
            "windows": rows,
        }

    def _error_result(self, provider: str, f: dict, error: str) -> dict:
        return {
            "provider": provider,
            "account": f.get("account") or f.get("email") or f.get("label") or f.get("name", ""),
            "name": f.get("name", ""),
            "plan": None,
            "disabled": self._is_disabled(f),
            "status": "error",
            "error": error,
            "windows": [],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    def _account_key(self, f: dict) -> str:
        return f.get("name", "") or f.get("account", "") or f.get("email", "")

    async def _get_files(self, client: httpx.AsyncClient) -> list[dict]:
        now = time.time()
        if self._files_cache and (now - self._files_cache_time) < self.cache_ttl:
            return self._files_cache
        files = await self._get_auth_files(client)
        self._files_cache = files
        self._files_cache_time = now
        return files

    def _fetcher_map(self):
        return {
            "codex": self._fetch_codex_quota,
            "claude": self._fetch_claude_quota,
            "antigravity": self._fetch_antigravity_quota,
            "gemini-cli": self._fetch_gemini_cli_quota,
            "kimi": self._fetch_kimi_quota,
        }

    async def _fetch_one(self, client: httpx.AsyncClient, f: dict) -> dict | None:
        provider = self._resolve_provider(f)
        fm = self._fetcher_map()
        if not provider or provider not in fm:
            return None
        if self._is_disabled(f):
            return None
        try:
            result = await fm[provider](client, f)
        except Exception as e:
            result = self._error_result(provider, f, str(e))
        result["fetched_at"] = datetime.now(timezone.utc).isoformat()
        result["name"] = f.get("name", "")
        key = self._account_key(f)
        if result.get("status") == "error":
            existing = self._account_cache.get(key)
            if existing and existing.get("status") == "success":
                existing["last_error"] = result.get("error", "")
                return existing
        self._account_cache[key] = result
        self._account_times[key] = time.time()
        return result

    async def fetch_all(self) -> dict:
        now = time.time()
        fm = self._fetcher_map()

        async with httpx.AsyncClient() as client:
            try:
                files = await self._get_files(client)
            except Exception as e:
                return {"quotas": list(self._account_cache.values()), "error": str(e)}

            tasks = []
            for f in files:
                provider = self._resolve_provider(f)
                if not provider or provider not in fm or self._is_disabled(f):
                    continue
                key = self._account_key(f)
                if key in self._account_cache and (now - self._account_times.get(key, 0)) < self.cache_ttl:
                    continue
                tasks.append(self._fetch_one(client, f))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        return {"quotas": list(self._account_cache.values())}

    async def refresh_all(self) -> dict:
        self._account_cache.clear()
        self._account_times.clear()
        self._files_cache = None
        fm = self._fetcher_map()

        async with httpx.AsyncClient() as client:
            try:
                files = await self._get_files(client)
            except Exception as e:
                return {"quotas": [], "error": str(e)}

            tasks = []
            for f in files:
                provider = self._resolve_provider(f)
                if not provider or provider not in fm or self._is_disabled(f):
                    continue
                tasks.append(self._fetch_one(client, f))

            await asyncio.gather(*tasks, return_exceptions=True)

        return {"quotas": list(self._account_cache.values())}

    async def refresh_account(self, account_name: str) -> dict:
        fm = self._fetcher_map()

        async with httpx.AsyncClient() as client:
            try:
                files = await self._get_files(client)
            except Exception as e:
                return {"quotas": list(self._account_cache.values()), "error": str(e)}

            target = None
            for f in files:
                if f.get("name", "") == account_name:
                    target = f
                    break
            if not target:
                for f in files:
                    acct = f.get("account") or f.get("email") or f.get("label") or ""
                    if acct == account_name:
                        target = f
                        break

            if target:
                await self._fetch_one(client, target)

        return {"quotas": list(self._account_cache.values())}
