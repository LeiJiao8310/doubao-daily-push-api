#!/usr/bin/env python3
"""
豆包玩儿法推荐每日推送脚本

功能：
1. 获取当前用户的 tenant_key
2. 从多维表格读取推送素材
3. 按「推送排期 = 今日」且「当前用户 tenant_key 在目标推送客户Tenant_Key 中」筛选
4. 生成飞书消息卡片 2.0 风格的 HTML
5. 自动以浏览器弹窗打开
"""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

# ============ 配置 ============
# Vercel 中间 API（由 Skill 发布方托管，用户无需配置）
DEFAULT_MIDDLE_API_URL = "https://doubao-daily-push-api.vercel.app"
DEFAULT_MIDDLE_API_KEY = "doubao_daily_push"

# 配置优先从环境变量读取；其次读取 Skill 包内默认配置。
# 旧版曾使用 ~/.doubao_daily_push/config.json，仅保留只读兼容，不再写入本地文件。
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_FILE = SKILL_DIR / "assets" / "default_config.json"
CONFIG_DIR = Path.home() / ".doubao_daily_push"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 字段名
FIELD_NAME = "素材名称"
FIELD_INTRO = "推文介绍"
FIELD_LINK = "原始链接"
FIELD_SCHEDULE = "推送排期"
FIELD_TENANT = "目标推送客户Tenant_Key"
FIELD_CATEGORY = "内容类别"


def run_lark_cli(args):
    """执行 lark-cli 命令并返回 JSON 结果，兼容 Windows 上的 lark-cli.exe。"""
    executable = shutil.which("lark-cli") or shutil.which("lark-cli.exe")
    if not executable:
        msg = "未找到 lark-cli，请确认当前运行环境已安装 lark-cli 并在 PATH 中"
        print("❌ " + msg, file=sys.stderr)
        return {"ok": False, "error": msg}

    cmd = [executable] + args + ["--format", "json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print("❌ lark-cli 执行失败: " + result.stderr, file=sys.stderr)
            return {"ok": False, "error": result.stderr}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print("❌ lark-cli 执行超时", file=sys.stderr)
        return {"ok": False, "error": "timeout"}
    except json.JSONDecodeError as e:
        print("❌ JSON 解析失败: " + str(e), file=sys.stderr)
        return {"ok": False, "error": str(e)}
    except FileNotFoundError as e:
        print("❌ lark-cli 不存在或无法执行: " + str(e), file=sys.stderr)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        print("❌ lark-cli 执行异常: " + str(e), file=sys.stderr)
        return {"ok": False, "error": str(e)}


def get_current_tenant_key():
    """获取当前登录用户的 tenant_key"""
    resp = run_lark_cli(["contact", "+get-user"])
    if resp.get("ok") and resp.get("data", {}).get("user", {}).get("tenant_key"):
        return resp["data"]["user"]["tenant_key"]
    print("❌ 无法获取当前用户的 tenant_key", file=sys.stderr)
    sys.exit(1)


def get_today_str():
    """获取今天的日期字符串 (YYYY-MM-DD)，使用东八区"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def load_json_config(path):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_config():
    return load_json_config(CONFIG_FILE)


def load_default_config():
    return load_json_config(DEFAULT_CONFIG_FILE)


def parse_bitable_url(url):
    parsed = urlparse(url.strip())
    match = re.search(r"/wiki/([^/?#]+)", parsed.path)
    wiki_token = match.group(1) if match else ""
    query = parse_qs(parsed.query)
    table_id = (query.get("table") or query.get("table_id") or [""])[0]
    return wiki_token, table_id


def ensure_config():
    """确保 wiki_token / table_id 已配置。

    配置优先级：
    1. 环境变量：DOUBAO_BITABLE_URL
    2. 环境变量：DOUBAO_WIKI_TOKEN / DOUBAO_TABLE_ID
    3. Skill 包内默认配置 assets/default_config.json
    4. 旧版本地配置文件（只读兼容，不再写入）

    不再在首次运行时交互输入并保存到 ~/.doubao_daily_push/config.json，避免客户新机器重复配置。
    """
    config = {}

    env_url = os.environ.get("DOUBAO_BITABLE_URL", "").strip()
    if env_url:
        wiki_token, table_id = parse_bitable_url(env_url)
        config["wiki_token"] = wiki_token
        config["table_id"] = table_id

    if not config.get("wiki_token") or not config.get("table_id"):
        env_wiki_token = os.environ.get("DOUBAO_WIKI_TOKEN", "").strip()
        env_table_id = os.environ.get("DOUBAO_TABLE_ID", "").strip()
        if env_wiki_token and env_table_id:
            config["wiki_token"] = env_wiki_token
            config["table_id"] = env_table_id

    if not config.get("wiki_token") or not config.get("table_id"):
        default_config = load_default_config()
        if default_config.get("wiki_token") and default_config.get("table_id"):
            config["wiki_token"] = default_config["wiki_token"]
            config["table_id"] = default_config["table_id"]

    if not config.get("wiki_token") or not config.get("table_id"):
        legacy_config = load_config()
        if legacy_config.get("wiki_token") and legacy_config.get("table_id"):
            config["wiki_token"] = legacy_config["wiki_token"]
            config["table_id"] = legacy_config["table_id"]

    if not config.get("wiki_token") or not config.get("table_id"):
        print("❌ 未找到多维表格链接配置。", file=sys.stderr)
        print("   请让 CSM 先配置并重新上传已配置版本的 Skill：我的表格链接是 <多维表格链接>。", file=sys.stderr)
        print("   配置会写入 Skill Variables，并固化到 Skill 包内 assets/default_config.json。", file=sys.stderr)
        sys.exit(1)

    # API 端点：默认走内置值，允许 Skill Variables / 环境变量覆盖（方便调试/内网替换）
    config["middle_api_url"] = os.environ.get("MIDDLE_API_URL", DEFAULT_MIDDLE_API_URL).rstrip("/")
    config["middle_api_key"] = os.environ.get("MIDDLE_API_KEY", DEFAULT_MIDDLE_API_KEY)

    return config


def fetch_records(config, tenant_key, today_str):
    """通过 Vercel 中间 API 获取已筛选记录，返回字段字典列表"""
    params = {
        "wiki_token": config["wiki_token"],
        "table_id": config["table_id"],
        "date": today_str,
        "tenant_key": tenant_key,
    }
    url = config["middle_api_url"].rstrip("/") + "/records?" + urlencode(params)
    resp = requests.get(url, headers={"X-API-Key": config["middle_api_key"]}, timeout=30)
    if resp.status_code != 200:
        print("❌ 获取记录失败: HTTP " + str(resp.status_code) + " " + resp.text, file=sys.stderr)
        sys.exit(1)
    payload = resp.json()
    if payload.get("error"):
        print("❌ 获取记录失败: " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    return [item.get("fields", {}) for item in payload.get("records", [])]


def filter_records(records, tenant_key, today_str):
    """
    筛选符合条件的记录：
    1. 推送排期 日期部分 == 今天
    2. 当前用户 tenant_key 在 目标推送客户Tenant_Key 中
    """
    matched = []
    for fields in records:
        # 检查推送排期
        schedule_val = fields.get(FIELD_SCHEDULE)
        if not schedule_val:
            continue
        # 日期格式: 2026-08-12T00:00:00.000+08:00 或时间戳
        if isinstance(schedule_val, str):
            schedule_date = schedule_val[:10]
        elif isinstance(schedule_val, (int, float)):
            dt = datetime.fromtimestamp(schedule_val / 1000, tz=timezone(timedelta(hours=8)))
            schedule_date = dt.strftime("%Y-%m-%d")
        else:
            continue

        if schedule_date != today_str:
            continue

        # 检查 tenant_key
        tenant_val = fields.get(FIELD_TENANT)
        if not tenant_val:
            continue
        # tenant_val 可能是逗号分隔的字符串或列表
        if isinstance(tenant_val, list):
            tenant_str = ",".join(str(v) for v in tenant_val)
        else:
            tenant_str = str(tenant_val)

        tenant_keys = [k.strip() for k in tenant_str.split(",")]
        if tenant_key not in tenant_keys:
            continue

        matched.append(fields)

    return matched


def extract_link_url(link_val):
    """从链接字段提取 URL"""
    if not link_val:
        return "#"
    if isinstance(link_val, str):
        if "](http" in link_val:
            start = link_val.find("](") + 2
            end = link_val.find(")", start)
            return link_val[start:end] if end > start else link_val
        if link_val.startswith("http"):
            return link_val
        return "#"
    if isinstance(link_val, list):
        for seg in link_val:
            if isinstance(seg, dict) and seg.get("link"):
                return seg["link"]
            if isinstance(seg, dict) and seg.get("text", "").startswith("http"):
                return seg["text"]
        full_text = "".join(
            seg.get("text", "") if isinstance(seg, dict) else str(seg)
            for seg in link_val
        )
        if full_text.startswith("http"):
            return full_text
    if isinstance(link_val, dict):
        return link_val.get("link", link_val.get("url", link_val.get("text", "#")))
    return "#"


def extract_text(text_val):
    """从 text 字段提取纯文本"""
    if not text_val:
        return ""
    if isinstance(text_val, str):
        return text_val
    if isinstance(text_val, list):
        return "".join(
            seg.get("text", "") if isinstance(seg, dict) else str(seg)
            for seg in text_val
        )
    if isinstance(text_val, dict):
        return text_val.get("text", "")
    return str(text_val)


def extract_category(cat_val):
    """从选择字段提取分类名称"""
    if not cat_val:
        return ""
    if isinstance(cat_val, str):
        return cat_val
    if isinstance(cat_val, list):
        return cat_val[0] if cat_val else ""
    if isinstance(cat_val, dict):
        return cat_val.get("name", cat_val.get("text", ""))
    return str(cat_val)


# 分类主题映射：按内容语义使用低饱和蓝、绿、暖橙三组填充色
CATEGORY_THEMES = {
    "Demo案例": "blue",
    "竞品对比": "blue",
    "GTM弹药": "blue",
    "打单心得": "green",
    "安全合规": "green",
    "流程权限": "green",
    "客户Q&A": "amber",
    "定价权益": "amber",
    "相关会议": "amber",
    "其他": "blue",
}


def escape_html(text):
    """转义 HTML 特殊字符"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def build_card_block(fields, is_last):
    """构建单个彩色内容卡片 HTML。"""
    name = escape_html(extract_text(fields.get(FIELD_NAME, "")))
    intro_raw = extract_text(fields.get(FIELD_INTRO, ""))
    intro = escape_html(intro_raw)
    link = escape_html(extract_link_url(fields.get(FIELD_LINK)))
    category = extract_category(fields.get(FIELD_CATEGORY, ""))
    theme = CATEGORY_THEMES.get(category, "blue")
    read_minutes = max(1, min(9, round(max(1, _weighted_text_len(intro_raw)) / 80)))

    tag_html = ""
    if category:
        tag_html = '<span class="tag">' + escape_html(category) + '</span>'

    return (
        '            <article class="item item-' + theme + '">\n'
        '              <div class="item-top">\n'
        '                ' + tag_html + '\n'
        '                <h2 class="item-title">' + name + '</h2>\n'
        '              </div>\n'
        '              <p class="item-desc">' + intro + '</p>\n'
        '              <div class="item-footer">\n'
        '                <span class="read-time">约 ' + str(read_minutes) + ' 分钟</span>\n'
        '                <a href="' + link + '" target="_blank" rel="noopener noreferrer" class="btn">\n'
        '                  <span>查看详情</span><span aria-hidden="true">›</span>\n'
        '                </a>\n'
        '              </div>\n'
        '            </article>\n'
    )


def _weighted_text_len(text: str) -> float:
    """估算文本的“等宽字符长度”。

    - 中文/全角字符按 1
    - ASCII（英文/数字/半角符号）按 0.5

    这是为了在不真实渲染的情况下，尽可能稳定地估算换行行数。
    """

    total = 0.0
    for ch in text:
        if ord(ch) < 128:
            total += 0.5
        else:
            total += 1.0
    return total


def _estimate_lines(text: str, chars_per_line: int) -> int:
    text = (text or "").strip()
    if not text:
        return 1
    # 粗略认为 \n 会强制换行
    parts = [p for p in text.splitlines() if p is not None]
    lines = 0
    for part in parts:
        wlen = _weighted_text_len(part)
        lines += max(1, int((wlen + chars_per_line - 1) // chars_per_line))
    return max(1, lines)


def compute_content_height(records) -> int:
    """根据 HTML/CSS 模板，在生成阶段估算内容高度（不含浏览器标题栏等 chrome 开销）。

    目标：让 open_popup.py 能用该高度直接设置 --window-size，避免依赖 JS resizeTo（--app 模式下通常无效）。

    计算范围：body padding + card-container 高度。
    """

    # ========= 基础尺寸（与 CSS 强绑定） =========
    BODY_PADDING_TB = 12 * 2

    CARD_WIDTH = 420
    CARD_BODY_PADDING_LR = 24 * 2
    CARD_BODY_INNER_WIDTH = CARD_WIDTH - CARD_BODY_PADDING_LR  # 372

    # header
    HEADER_PADDING_TOP = 24
    HEADER_PADDING_BOTTOM = 20
    TITLE_FONT = 18
    TITLE_LINE_HEIGHT = 1.4
    SUBTITLE_FONT = 13
    SUBTITLE_LINE_HEIGHT = 1.2  # CSS 未显式写 line-height，取较常见的 1.2 做近似
    SUBTITLE_MARGIN_TOP = 6

    # body
    CARD_BODY_PADDING_TOP = 20
    CARD_BODY_PADDING_BOTTOM = 24

    # block
    BLOCK_PADDING_TB = 16 * 2
    BLOCK_HEADER_MARGIN_BOTTOM = 8
    BLOCK_TITLE_FONT = 15
    BLOCK_TITLE_LINE_HEIGHT = 1.5
    BLOCK_DESC_FONT = 14
    BLOCK_DESC_LINE_HEIGHT = 1.7
    BLOCK_DESC_MARGIN_BOTTOM = 12
    BTN_PADDING_TB = 8 * 2
    BTN_FONT = 13
    BTN_LINE_HEIGHT = 1.2
    DIVIDER_HEIGHT = 1

    # ========= header 高度 =========
    header_title_lines = 1
    header_height = (
        HEADER_PADDING_TOP
        + (TITLE_FONT * TITLE_LINE_HEIGHT * header_title_lines)
        + SUBTITLE_MARGIN_TOP
        + (SUBTITLE_FONT * SUBTITLE_LINE_HEIGHT)
        + HEADER_PADDING_BOTTOM
    )

    # ========= body 高度 =========
    if not records:
        # empty-state
        EMPTY_PADDING_TB = 48 * 2
        EMPTY_SVG = 48
        EMPTY_SVG_MB = 16
        EMPTY_P_FONT = 14
        EMPTY_P_LINE_HEIGHT = 1.6
        # 文案中有 <br>，按两行估算
        empty_text_lines = 2
        empty_height = (
            EMPTY_PADDING_TB
            + EMPTY_SVG
            + EMPTY_SVG_MB
            + (EMPTY_P_FONT * EMPTY_P_LINE_HEIGHT * empty_text_lines)
        )
        card_body_inner_height = empty_height
    else:
        # 估算每个 block 的高度
        desc_chars_per_line = max(10, int(CARD_BODY_INNER_WIDTH // BLOCK_DESC_FONT))  # 372/14≈26

        # 标题因为有 tag（可换行）会更难估算：有 tag 时给标题减少一些可用宽度
        title_width_with_tag = max(120, CARD_BODY_INNER_WIDTH - 80)
        title_cpl_with_tag = max(8, int(title_width_with_tag // BLOCK_TITLE_FONT))
        title_cpl_no_tag = max(8, int(CARD_BODY_INNER_WIDTH // BLOCK_TITLE_FONT))

        blocks_total = 0.0
        for idx, fields in enumerate(records):
            category = extract_category(fields.get(FIELD_CATEGORY, ""))
            title = extract_text(fields.get(FIELD_NAME, ""))
            intro = extract_text(fields.get(FIELD_INTRO, ""))

            title_lines = _estimate_lines(title, title_cpl_with_tag if category else title_cpl_no_tag)
            desc_lines = _estimate_lines(intro, desc_chars_per_line)

            block_header_height = (BLOCK_TITLE_FONT * BLOCK_TITLE_LINE_HEIGHT * title_lines) + BLOCK_HEADER_MARGIN_BOTTOM
            block_desc_height = (BLOCK_DESC_FONT * BLOCK_DESC_LINE_HEIGHT * desc_lines) + BLOCK_DESC_MARGIN_BOTTOM
            btn_height = BTN_PADDING_TB + (BTN_FONT * BTN_LINE_HEIGHT)

            block_height = BLOCK_PADDING_TB + block_header_height + block_desc_height + btn_height
            blocks_total += block_height

            if idx != len(records) - 1:
                blocks_total += DIVIDER_HEIGHT

        card_body_inner_height = blocks_total

    card_height = header_height + CARD_BODY_PADDING_TOP + card_body_inner_height + CARD_BODY_PADDING_BOTTOM
    content_height = BODY_PADDING_TB + card_height

    # 与像素对齐，向上取整，避免裁切
    return int(content_height + 0.9999)


def generate_html(records, today_str):
    """生成飞书消息卡片 2.0 风格的 HTML"""

    # 生成卡片内容块
    cards_html = ""
    for i, fields in enumerate(records):
        is_last = (i == len(records) - 1)
        cards_html += build_card_block(fields, is_last)

    if not cards_html:
        cards_html = (
            '            <div class="empty-state">\n'
            '              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">\n'
            '                <circle cx="24" cy="24" r="20" stroke="#DEE0E3" stroke-width="2"/>\n'
            '                <path d="M16 24h16M24 16v16" stroke="#DEE0E3" stroke-width="2" stroke-linecap="round"/>\n'
            '              </svg>\n'
            '              <p>今日暂无推送内容<br>明天见！&#128075;</p>\n'
            '            </div>\n'
        )

    display_date = today_str.replace("-", "/")

    # 计算内容尺寸（不含浏览器 chrome），供 open_popup.py 直接使用
    content_width = 444  # 420 + body 左右 padding(12*2)
    content_height = compute_content_height(records)

    html_template = """<!DOCTYPE html>
<html lang="zh-CN" data-content-width="{{CONTENT_WIDTH}}" data-content-height="{{CONTENT_HEIGHT}}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>豆包玩儿法推荐每日一更！</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        html, body {
            width: 100%;
            height: auto;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: #EEF3F8;
            color: #243042;
            padding: 12px;
            display: flex;
            justify-content: center;
            align-items: flex-start;
        }
        .card-container {
            width: 420px;
            max-width: 420px;
            background: #F8FAFC;
            border: 1px solid rgba(64, 84, 112, 0.08);
            border-radius: 8px;
            box-shadow: 0 8px 28px rgba(36, 48, 66, 0.10);
            overflow: hidden;
        }
        .card-header {
            background: linear-gradient(135deg, #316BD6 0%, #2454B7 100%);
            color: #FFFFFF;
            padding: 22px 22px 18px;
            position: relative;
            overflow: hidden;
        }
        .card-header::before {
            content: '';
            position: absolute;
            width: 124px;
            height: 124px;
            right: -42px;
            top: -54px;
            border-radius: 50%;
            background: rgba(255,255,255,0.12);
        }
        .card-header::after {
            content: '';
            position: absolute;
            width: 76px;
            height: 76px;
            right: 62px;
            bottom: -50px;
            border: 14px solid rgba(255,255,255,0.07);
            border-radius: 50%;
        }
        .eyebrow {
            position: relative;
            z-index: 1;
            margin-bottom: 6px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 1.4px;
            opacity: 0.78;
        }
        .card-title {
            position: relative;
            z-index: 1;
            font-size: 18px;
            font-weight: 700;
            color: #FFFFFF;
            line-height: 1.4;
        }
        .card-subtitle {
            position: relative;
            z-index: 1;
            margin-top: 5px;
            font-size: 12px;
            color: rgba(255,255,255,0.78);
        }
        .card-body {
            display: grid;
            gap: 10px;
            padding: 14px;
        }
        .item {
            position: relative;
            overflow: hidden;
            padding: 14px 14px 13px 17px;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: var(--fill);
            box-shadow: 0 3px 12px rgba(38,56,80,0.06);
            transition: transform 0.18s ease-out, box-shadow 0.18s ease-out;
        }
        .item::before {
            content: '';
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: var(--accent);
        }
        .item:hover {
            transform: translateY(-2px);
            box-shadow: 0 7px 18px rgba(38,56,80,0.11);
        }
        .item-blue { --fill:#EDF5FF; --line:#D4E6FB; --accent:#3478D4; --tag-bg:#D8EAFE; --tag-text:#225DA8; --button:#2F70C7; --button-hover:#255DA7; }
        .item-green { --fill:#EEF8F2; --line:#D4EADC; --accent:#3A9562; --tag-bg:#D9EFE1; --tag-text:#276C45; --button:#318154; --button-hover:#286A45; }
        .item-amber { --fill:#FFF7E9; --line:#F1E0BF; --accent:#C98226; --tag-bg:#F8E6C7; --tag-text:#855414; --button:#B87320; --button-hover:#965C19; }
        .item-top {
            display: flex;
            align-items: flex-start;
            gap: 9px;
        }
        .tag {
            flex: 0 0 auto;
            margin-top: 1px;
            padding: 3px 7px;
            border-radius: 4px;
            background: var(--tag-bg);
            color: var(--tag-text);
            font-size: 11px;
            font-weight: 650;
            line-height: 1.3;
        }
        .item-title {
            font-size: 15px;
            font-weight: 700;
            line-height: 1.45;
            color: #202C3D;
        }
        .item-desc {
            margin: 8px 0 11px;
            font-size: 13px;
            line-height: 1.65;
            color: #566477;
        }
        .item-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .read-time { font-size: 11px; color: #7A8797; }
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 6px 10px;
            border-radius: 4px;
            background: var(--button);
            color: #FFFFFF;
            font-size: 12px;
            font-weight: 600;
            text-decoration: none;
            transition: background 0.18s ease-out, transform 0.18s ease-out;
        }
        .btn:hover { background: var(--button-hover); transform: translateX(1px); }
        .empty-state {
            text-align: center;
            padding: 48px 24px;
            color: #8F959E;
        }
        .empty-state svg {
            margin-bottom: 16px;
        }
        .empty-state p {
            font-size: 14px;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <div class="card-container">
        <div class="card-header">
            <div class="eyebrow">DAILY PICKS</div>
            <div class="card-title">豆包玩儿法推荐每日一更！</div>
            <div class="card-subtitle">&#128197; {{DATE}} · 今日 {{COUNT}} 条精选</div>
        </div>
        <div class="card-body">
{{CARDS}}
        </div>
    </div>
    <script>
        // 说明：在 Chrome/Edge --app 模式下，命令行启动的独立窗口通常无法被 resizeTo/moveTo 调整。
        // 因此窗口尺寸改由 open_popup.py 在启动阶段读取 <html data-content-*> 并一次性设置。

        // fallback 弹窗逻辑（当默认浏览器标签页打开时）
        (function() {
            var isAppMode = !window.menubar || !window.menubar.visible;
            if (!isAppMode && !window.opener) {
                var w = 420, h = 600;
                var left = Math.round((screen.width - w) / 2);
                var top = Math.round((screen.height - h) / 2);
                var features = [
                    'width=' + w, 'height=' + h,
                    'left=' + left, 'top=' + top,
                    'scrollbars=yes', 'resizable=yes',
                    'menubar=no', 'toolbar=no', 'location=no', 'status=no'
                ].join(',');
                var popup = window.open(window.location.href, 'doubao_daily_push', features);
                if (popup && !popup.closed) {
                    document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#8F959E;font-size:14px;">已在弹窗中打开，可关闭此标签页</div>';
                }
            }
        })();
    </script>
</body>
</html>"""

    html = (
        html_template
        .replace("{{DATE}}", display_date)
        .replace("{{COUNT}}", str(len(records)))
        .replace("{{CARDS}}", cards_html)
        .replace("{{CONTENT_WIDTH}}", str(content_width))
        .replace("{{CONTENT_HEIGHT}}", str(content_height))
    )
    return html


def main():
    print("🚀 豆包玩儿法推荐 - 每日推送生成中...")

    # 1. 准备配置
    print("⚙️ 读取/初始化配置...")
    config = ensure_config()
    print("   ✅ 配置就绪: Skill Variables / 环境变量")
    print("   📎 数据源: " + config["wiki_token"] + " / " + config["table_id"])
    print("   🌐 中间 API: " + config["middle_api_url"])

    # 2. 获取 tenant_key
    print("📌 获取当前用户 tenant_key...")
    tenant_key = get_current_tenant_key()
    print("   ✅ tenant_key: " + tenant_key)

    # 3. 获取今天日期
    today_str = get_today_str()
    print("📅 今日日期: " + today_str)

    # 4. 通过 Vercel 中间 API 获取已筛选记录
    print("📖 从中间 API 获取今日推送记录...")
    matched = fetch_records(config, tenant_key, today_str)
    print("   ✅ 获取到 " + str(len(matched)) + " 条今日推送")

    # 5. 生成 HTML
    print("🎨 生成 HTML 卡片...")
    html_content = generate_html(matched, today_str)

    # 6. 写入文件
    output_dir = os.environ.get("WORKSPACE_PATH", os.getcwd())
    output_file = os.path.join(output_dir, "doubao_daily_push.html")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("   ✅ HTML 已生成: " + output_file)

    print("")
    print("✨ 推送生成完成！请将 HTML 传输到本地并用 open_popup.py 打开。")
    return output_file


if __name__ == "__main__":
    main()
