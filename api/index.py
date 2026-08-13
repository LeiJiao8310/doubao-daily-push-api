import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    """Allow browser clients such as Feishu Miaoda to call every API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response

LARK_OPEN_API = "https://open.feishu.cn/open-apis"
APP_ID = os.getenv("LARK_APP_ID", "")
APP_SECRET = os.getenv("LARK_APP_SECRET", "")
API_KEY = os.getenv("MIDDLE_API_KEY", "")

DATE_FIELD = "推送排期"
TENANT_KEY_FIELD = "目标推送客户Tenant_Key"
DEFAULT_PAGE_SIZE = 100

REGISTRY_BASE_TOKEN = os.getenv("REGISTRY_BASE_TOKEN", "FRh9bKHGCah9HlsczKTc1gCPn4d")
REGISTRY_TABLE_ID = os.getenv("REGISTRY_TABLE_ID", "tblg8QBggPlVm0kV")
REGISTRY_WIKI_FIELD = "wiki_token"
REGISTRY_LAST_PUSH_FIELD = "最近推送时间"
REGISTRY_PUSH_COUNT_FIELD = "累计推送次数"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_TEMPLATE_DIR = PROJECT_ROOT / "skill_template"
BUILD_MIDDLE_API_URL = "https://doubao-daily-push-api.vercel.app"
BUILD_MIDDLE_API_KEY = "doubao_daily_push"

_token_cache: Dict[str, Any] = {"token": None, "expire_at": 0}
_base_token_cache: Dict[str, Any] = {}


def now_ts() -> int:
    return int(time.time())


def today_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def require_api_key() -> Optional[Any]:
    if not API_KEY:
        return jsonify({"error": "server_missing_api_key_config"}), 500
    given = request.headers.get("X-API-Key") or request.args.get("api_key")
    if given != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    return None


def require_query_params() -> Tuple[Optional[str], Optional[str], Optional[Any]]:
    wiki_token = (request.args.get("wiki_token") or "").strip()
    table_id = (request.args.get("table_id") or "").strip()
    if not wiki_token:
        return None, None, (jsonify({"error": "missing_wiki_token"}), 400)
    if not table_id:
        return None, None, (jsonify({"error": "missing_table_id"}), 400)
    return wiki_token, table_id, None


def lark_post(path: str, body: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(f"{LARK_OPEN_API}{path}", json=body, headers=headers, timeout=15)
    try:
        data = resp.json()
    except ValueError:
        data = {"raw_response": resp.text[:1000]}
    if not resp.ok:
        raise RuntimeError(
            f"Lark API HTTP error path={path}, status={resp.status_code}, response={data}"
        )
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Lark API error path={path}, code={data.get('code')}, msg={data.get('msg')}")
    return data


def lark_get(path: str, token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{LARK_OPEN_API}{path}", headers=headers, params=params or {}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Lark API error path={path}, code={data.get('code')}, msg={data.get('msg')}")
    return data


def lark_put(path: str, body: Dict[str, Any], token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    resp = requests.put(f"{LARK_OPEN_API}{path}", json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Lark API error path={path}, code={data.get('code')}, msg={data.get('msg')}")
    return data


def get_tenant_access_token() -> str:
    if _token_cache["token"] and _token_cache["expire_at"] > now_ts() + 60:
        return _token_cache["token"]
    if not APP_ID:
        raise RuntimeError("LARK_APP_ID is not configured. Set it in Vercel Environment Variables.")
    if not APP_SECRET:
        raise RuntimeError("LARK_APP_SECRET is not configured. Set it in Vercel Environment Variables, not in code.")
    data = lark_post("/auth/v3/tenant_access_token/internal", {
        "app_id": APP_ID,
        "app_secret": APP_SECRET,
    })
    token = data["tenant_access_token"]
    expire = int(data.get("expire", 7200))
    _token_cache.update({"token": token, "expire_at": now_ts() + expire})
    return token


def get_base_token_from_wiki(wiki_token: str) -> str:
    cached = _base_token_cache.get(wiki_token)
    if cached and cached["expire_at"] > now_ts() + 300:
        return cached["base_token"]
    token = get_tenant_access_token()
    data = lark_get("/wiki/v2/spaces/get_node", token, params={"token": wiki_token})
    node = data.get("data", {}).get("node", {})
    obj_token = node.get("obj_token")
    obj_type = node.get("obj_type")
    if not obj_token:
        raise RuntimeError("wiki node obj_token not found")
    if obj_type and obj_type != "bitable":
        raise RuntimeError(f"wiki node is not bitable, obj_type={obj_type}")
    _base_token_cache[wiki_token] = {"base_token": obj_token, "expire_at": now_ts() + 3600}
    return obj_token


def normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, (int, float)):
        ts = int(value)
        if ts > 10_000_000_000:
            ts = ts // 1000
        return datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    return str(value)[:10]


def field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or item.get("value") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("value") or value)
    return str(value)


def list_records(base_token: str, table_id: str) -> List[Dict[str, Any]]:
    token = get_tenant_access_token()
    records: List[Dict[str, Any]] = []
    page_token = None
    while True:
        params = {"page_size": DEFAULT_PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token
        data = lark_get(f"/bitable/v1/apps/{base_token}/tables/{table_id}/records", token, params=params)
        payload = data.get("data", {})
        records.extend(payload.get("items", []))
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token")
        if not page_token:
            break
    return records


def tenant_matches(field_value: Any, tenant_key: str) -> bool:
    if not tenant_key:
        return True
    tenant_str = field_text(field_value)
    tenant_keys = [item.strip() for item in tenant_str.split(",") if item.strip()]
    return tenant_key in tenant_keys


def filter_records(records: List[Dict[str, Any]], date: str, tenant_key: Optional[str]) -> List[Dict[str, Any]]:
    result = []
    for record in records:
        fields = record.get("fields", {})
        record_date = normalize_date(fields.get(DATE_FIELD))
        if record_date != date:
            continue
        if tenant_key and not tenant_matches(fields.get(TENANT_KEY_FIELD), tenant_key):
            continue
        result.append({
            "record_id": record.get("record_id"),
            "fields": fields,
        })
    return result


def timestamp_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value if value > 10_000_000_000 else value * 1000)
    text = str(value or "").strip()
    if not text:
        return int(time.time() * 1000)
    try:
        normalized = text.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except ValueError:
        return int(float(text) * (1 if float(text) > 10_000_000_000 else 1000))


def find_registry_record(wiki_token: str) -> Optional[Dict[str, Any]]:
    for record in list_records(REGISTRY_BASE_TOKEN, REGISTRY_TABLE_ID):
        if field_text(record.get("fields", {}).get(REGISTRY_WIKI_FIELD)).strip() == wiki_token:
            return record
    return None


def create_registration(payload: Dict[str, Any]) -> str:
    token = get_tenant_access_token()
    fields = {
        "CSM 姓名": payload["csm_name"],
        "邮箱": payload["email"],
        "user_id": payload["user_id"],
        REGISTRY_WIKI_FIELD: payload["wiki_token"],
        "注册时间": timestamp_ms(payload.get("timestamp")),
        REGISTRY_PUSH_COUNT_FIELD: 0,
    }
    data = lark_post(
        f"/bitable/v1/apps/{REGISTRY_BASE_TOKEN}/tables/{REGISTRY_TABLE_ID}/records",
        {"fields": fields},
        token,
    )
    return data.get("data", {}).get("record", {}).get("record_id", "")


def update_registration_push_stats(wiki_token: str) -> bool:
    record = find_registry_record(wiki_token)
    if not record:
        return False
    record_id = record.get("record_id")
    current_count = record.get("fields", {}).get(REGISTRY_PUSH_COUNT_FIELD) or 0
    try:
        current_count = int(float(current_count))
    except (TypeError, ValueError):
        current_count = 0
    token = get_tenant_access_token()
    lark_put(
        f"/bitable/v1/apps/{REGISTRY_BASE_TOKEN}/tables/{REGISTRY_TABLE_ID}/records/{record_id}",
        {"fields": {
            REGISTRY_LAST_PUSH_FIELD: int(time.time() * 1000),
            REGISTRY_PUSH_COUNT_FIELD: current_count + 1,
        }},
        token,
    )
    return True


@app.get("/health")
def health():
    return jsonify({"ok": True})


def parse_bitable_url(url: str) -> Tuple[str, str]:
    parsed = urlparse(url.strip())
    match = re.search(r"/wiki/([^/?#]+)", parsed.path)
    wiki_token = match.group(1) if match else ""
    query = parse_qs(parsed.query)
    table_id = (query.get("table") or query.get("table_id") or [""])[0]
    return wiki_token, table_id


def build_skill_zip(wiki_token: str, table_id: str) -> io.BytesIO:
    required_files = [
        "SKILL.md",
        "scripts/generate_daily_push.py",
        "scripts/open_popup.py",
    ]
    buffer = io.BytesIO()
    config = {
        "wiki_token": wiki_token,
        "table_id": table_id,
        "middle_api_url": BUILD_MIDDLE_API_URL,
        "middle_api_key": BUILD_MIDDLE_API_KEY,
    }
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel_path in required_files:
            source = SKILL_TEMPLATE_DIR / rel_path
            if not source.is_file():
                raise RuntimeError(f"missing skill template file: {rel_path}")
            archive.write(source, rel_path)
        archive.writestr("assets/default_config.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    buffer.seek(0)
    return buffer


@app.post("/build")
def build():
    auth_error = require_api_key()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    bitable_url = str(payload.get("bitable_url", "")).strip()
    wiki_token, table_id = parse_bitable_url(bitable_url)
    if not wiki_token or not table_id:
        return jsonify({"error": "invalid_bitable_url"}), 400
    try:
        return send_file(
            build_skill_zip(wiki_token, table_id),
            mimetype="application/zip",
            as_attachment=True,
            download_name="doubao-daily-push.zip",
        )
    except Exception as exc:
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@app.post("/register")
def register():
    auth_error = require_api_key()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    required = ["wiki_token", "csm_name", "email", "user_id", "timestamp"]
    missing = [name for name in required if not str(payload.get(name, "")).strip()]
    if missing:
        return jsonify({"error": "missing_fields", "fields": missing}), 400
    try:
        record_id = create_registration(payload)
        return jsonify({"ok": True, "record_id": record_id}), 201
    except Exception as exc:
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@app.get("/records")
def records():
    auth_error = require_api_key()
    if auth_error:
        return auth_error
    wiki_token, table_id, param_error = require_query_params()
    if param_error:
        return param_error
    date = request.args.get("date") or today_cst()
    tenant_key = request.args.get("tenant_key")
    try:
        base_token = get_base_token_from_wiki(wiki_token)
        all_records = list_records(base_token, table_id)
        items = filter_records(all_records, date=date, tenant_key=tenant_key)
        stats_updated = False
        try:
            stats_updated = update_registration_push_stats(wiki_token)
        except Exception as exc:
            app.logger.warning("failed to update registry stats for wiki_token=%s: %s", wiki_token, exc)
        return jsonify({
            "date": date,
            "tenant_key": tenant_key,
            "wiki_token": wiki_token,
            "table_id": table_id,
            "count": len(items),
            "records": items,
            "registry_stats_updated": stats_updated,
        })
    except Exception as exc:
        return jsonify({"error": "internal_error", "message": str(exc)}), 500
