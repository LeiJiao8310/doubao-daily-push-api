import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

LARK_OPEN_API = os.getenv("LARK_OPEN_API", "https://open.feishu.cn/open-apis")
APP_ID = os.getenv("LARK_APP_ID", "cli_aae68c4f4e789bc9")
APP_SECRET = os.getenv("LARK_APP_SECRET", "")
API_KEY = os.getenv("MIDDLE_API_KEY", "")
WIKI_TOKEN = os.getenv("LARK_WIKI_TOKEN", "XzprwzxmuiwHBUkYMcIcPZXBn0g")
TABLE_ID = os.getenv("LARK_TABLE_ID", "tblcyon9vA9y1BLx")
DATE_FIELD = os.getenv("DATE_FIELD", "date")
TENANT_KEY_FIELD = os.getenv("TENANT_KEY_FIELD", "tenant_key")
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "100"))

_token_cache: Dict[str, Any] = {"token": None, "expire_at": 0}
_base_token_cache: Dict[str, Any] = {"base_token": None, "expire_at": 0}


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


def lark_post(path: str, body: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(f"{LARK_OPEN_API}{path}", json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
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


def get_tenant_access_token() -> str:
    if _token_cache["token"] and _token_cache["expire_at"] > now_ts() + 60:
        return _token_cache["token"]
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


def get_base_token_from_wiki() -> str:
    if _base_token_cache["base_token"] and _base_token_cache["expire_at"] > now_ts() + 300:
        return _base_token_cache["base_token"]
    token = get_tenant_access_token()
    data = lark_get("/wiki/v2/spaces/get_node", token, params={"token": WIKI_TOKEN})
    node = data.get("data", {}).get("node", {})
    obj_token = node.get("obj_token")
    obj_type = node.get("obj_type")
    if not obj_token:
        raise RuntimeError("wiki node obj_token not found")
    if obj_type and obj_type != "bitable":
        raise RuntimeError(f"wiki node is not bitable, obj_type={obj_type}")
    _base_token_cache.update({"base_token": obj_token, "expire_at": now_ts() + 3600})
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


def list_records(base_token: str) -> List[Dict[str, Any]]:
    token = get_tenant_access_token()
    records: List[Dict[str, Any]] = []
    page_token = None
    while True:
        params = {"page_size": DEFAULT_PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token
        data = lark_get(f"/bitable/v1/apps/{base_token}/tables/{TABLE_ID}/records", token, params=params)
        payload = data.get("data", {})
        records.extend(payload.get("items", []))
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token")
        if not page_token:
            break
    return records


def filter_records(records: List[Dict[str, Any]], date: str, tenant_key: Optional[str]) -> List[Dict[str, Any]]:
    result = []
    for record in records:
        fields = record.get("fields", {})
        record_date = normalize_date(fields.get(DATE_FIELD))
        record_tenant = field_text(fields.get(TENANT_KEY_FIELD))
        if record_date != date:
            continue
        if tenant_key and record_tenant != tenant_key:
            continue
        result.append({
            "record_id": record.get("record_id"),
            "fields": fields,
        })
    return result


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/records")
def records():
    auth_error = require_api_key()
    if auth_error:
        return auth_error
    date = request.args.get("date") or today_cst()
    tenant_key = request.args.get("tenant_key")
    try:
        base_token = get_base_token_from_wiki()
        all_records = list_records(base_token)
        items = filter_records(all_records, date=date, tenant_key=tenant_key)
        return jsonify({
            "date": date,
            "tenant_key": tenant_key,
            "count": len(items),
            "records": items,
        })
    except Exception as exc:
        return jsonify({"error": "internal_error", "message": str(exc)}), 500
