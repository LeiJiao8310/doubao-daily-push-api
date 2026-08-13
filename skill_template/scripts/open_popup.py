#!/usr/bin/env python3
"""
本地弹窗打开脚本

在客户本地电脑执行，以 Chrome/Edge --app 模式或系统浏览器打开指定 HTML 文件。
兼容 macOS / Windows / Linux。
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path


def _existing_files(paths):
    return [str(Path(p)) for p in paths if p and Path(p).is_file()]


def find_browser():
    """
    查找可用的浏览器路径，优先 Chrome / Edge（支持 --app 模式）。
    返回 (path, browser_type)，browser_type 为 'chrome'|'edge'|'fallback'
    """
    system = platform.system()

    chrome_candidates = []
    edge_candidates = []

    if system == "Darwin":
        chrome_candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        edge_candidates = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            str(Path.home() / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
    elif system == "Windows":
        program_files = [
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        for base in program_files:
            if not base:
                continue
            chrome_candidates.extend([
                str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(Path(base) / "Google" / "Chrome Beta" / "Application" / "chrome.exe"),
                str(Path(base) / "Google" / "Chrome SxS" / "Application" / "chrome.exe"),
            ])
            edge_candidates.extend([
                str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(Path(base) / "Microsoft" / "Edge Beta" / "Application" / "msedge.exe"),
                str(Path(base) / "Microsoft" / "Edge SxS" / "Application" / "msedge.exe"),
            ])
        chrome_candidates.extend(["chrome.exe", "chrome"])
        edge_candidates.extend(["msedge.exe", "msedge"])
    else:  # Linux
        chrome_candidates = ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]
        edge_candidates = ["microsoft-edge", "microsoft-edge-stable"]

    for candidate in chrome_candidates:
        found = str(Path(candidate)) if Path(candidate).is_absolute() and Path(candidate).is_file() else shutil.which(candidate)
        if found:
            return (found, "chrome")

    for candidate in edge_candidates:
        found = str(Path(candidate)) if Path(candidate).is_absolute() and Path(candidate).is_file() else shutil.which(candidate)
        if found:
            return (found, "edge")

    return (None, "fallback")


def _parse_window_size_from_html(html_file):
    """从生成的 HTML 中解析 data-content-width / data-content-height。"""
    try:
        content = Path(html_file).read_text(encoding="utf-8")
    except Exception:
        return (None, None)

    import re

    m_w = re.search(r"data-content-width=\"(\d+)\"", content)
    m_h = re.search(r"data-content-height=\"(\d+)\"", content)
    if not (m_w and m_h):
        return (None, None)
    try:
        return (int(m_w.group(1)), int(m_h.group(1)))
    except Exception:
        return (None, None)


def _file_uri(html_file):
    """生成跨平台 file:// URI。Windows 不能用 'file://' + abspath 拼接。"""
    return Path(html_file).resolve().as_uri()


def _open_with_system(html_file, file_url):
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(html_file)])
        print("✅ 已通过 macOS open 命令打开")
        return True
    if system == "Windows":
        try:
            os.startfile(str(Path(html_file).resolve()))  # type: ignore[attr-defined]
            print("✅ 已通过 Windows 默认应用打开")
            return True
        except Exception:
            pass
    webbrowser.open(file_url)
    print("✅ 已用系统默认浏览器打开")
    return True


def open_as_popup(html_file):
    """以 pop-up 弹窗方式打开 HTML 文件。"""
    html_path = Path(html_file).resolve()
    file_url = _file_uri(html_path)

    content_w, content_h = _parse_window_size_from_html(html_path)
    default_w = 444
    default_h = 480
    if content_w is None or content_h is None:
        print("⚠️ 未能从 HTML 解析 data-content-width/height，将使用兜底窗口尺寸")
        content_w, content_h = default_w, default_h

    system = platform.system()
    chrome_height = 36 if system == "Darwin" else 48 if system == "Windows" else 32
    chrome_width = 0

    window_w = max(360, min(content_w + chrome_width, 900))
    window_h = max(240, min(content_h + chrome_height, 1200))

    browser_path, browser_type = find_browser()
    if browser_type in ("chrome", "edge"):
        user_data_dir = tempfile.mkdtemp(prefix="doubao_daily_push_profile_")
        cmd = [
            browser_path,
            "--user-data-dir=" + user_data_dir,
            "--app=" + file_url,
            "--window-size=" + str(window_w) + "," + str(window_h),
            "--window-position=200,120",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if system != "Windows":
            cmd.append("--disable-dev-shm-usage")

        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=(system != "Windows"))
            print(
                "✅ 已以 "
                + browser_type.capitalize()
                + " --app 弹窗模式打开"
                + "（--window-size="
                + str(window_w)
                + ","
                + str(window_h)
                + ", content="
                + str(content_w)
                + "x"
                + str(content_h)
                + ", chrome+="
                + str(chrome_height)
                + ", user-data-dir="
                + user_data_dir
                + ")"
            )
            return True
        except Exception as e:
            print("⚠️ " + browser_type.capitalize() + " --app 模式失败: " + str(e))

    try:
        return _open_with_system(html_path, file_url)
    except Exception as e:
        print("❌ 无法打开浏览器: " + str(e))
        return False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 open_popup.py <html文件路径>")
        sys.exit(1)

    html_file = Path(sys.argv[1]).expanduser()
    if not html_file.is_file():
        print("❌ 文件不存在: " + str(html_file))
        sys.exit(1)

    print("🌐 正在打开本地弹窗...")
    success = open_as_popup(html_file)
    if not success:
        print("📎 请手动打开: " + str(html_file.resolve()))
        sys.exit(1)


if __name__ == "__main__":
    main()
