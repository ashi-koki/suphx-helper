#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小苏菲 (majsoul 雀魂) 命令行启动器 —— 纯标准库、零第三方依赖。

复刻小苏菲 exe 打开系统 Chrome 的方式(使用相同的 user-data-dir)，实现登录持久化：
登录一次后，重复调用无需再次登录，登录会话与小苏菲 exe 完全共享。

详细用法见同目录 README.md。
"""

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# 强制 UTF-8 输出，避免 Windows 控制台中文乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Windows 下静默启动子进程(不弹控制台窗口)；非 Windows 下为 0(无效果)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---- 路径与常量 -----------------------------------------------------------

try:
    ROOT = Path(__file__).resolve().parent            # 本脚本所在目录(即小苏菲目录)
except NameError:  # 某些内嵌执行环境(如 runpy/exec)可能没有 __file__
    ROOT = Path.cwd()

INTERNAL = ROOT / "_internal"
DATA_DIR = INTERNAL / "data"                         # Chrome 用户目录(登录持久化处)
SETTINGS_PATH = INTERNAL / "settings.json"
APP_EXE = INTERNAL / "suphx.exe"                     # 主程序(Nuitka 编译)
LAUNCHER_EXE = ROOT / "1.首次右键管理员启动小苏菲.exe"

DEFAULT_URL = "https://game.maj-soul.com/1/"
DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 雀魂登录 token 的形态: access_token 后紧跟一个 UUID
_TOKEN_RE = re.compile(
    rb"access_token.{0,40}?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _print(*args, **kwargs):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(*args, **kwargs)


def load_settings():
    """读取主程序的 settings.json，尽量与其配置保持一致。"""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def find_chrome(settings):
    """优先用自定义浏览器路径，否则用系统 Chrome，最后兜底 PATH 里的浏览器。"""
    custom = (settings.get("custom_browser_path") or "").strip()
    if custom and Path(custom).exists():
        return custom
    if Path(DEFAULT_CHROME).exists():
        return DEFAULT_CHROME
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _detect_login_from_disk():
    """读 Chrome 的 localStorage leveldb 文件，判断 access_token 是否已写入。

    返回 (logged_in: bool, detail: str)。尽力而为——若文件被 Chrome 锁定读不到，
    返回未登录(而非报错)，配合 --timeout / 回车兜底。
    """
    leveldb = DATA_DIR / "Default" / "Local Storage" / "leveldb"
    if not leveldb.exists():
        return False, "leveldb 目录不存在"
    buf = bytearray()
    files = sorted(leveldb.glob("*.log")) + sorted(leveldb.glob("*.ldb"))
    if not files:
        return False, "leveldb 无数据文件"
    for f in files:
        try:
            buf += f.read_bytes()
        except OSError:
            continue
    if _TOKEN_RE.search(bytes(buf)):
        return True, "检测到 access_token(已登录)"
    return False, "尚未检测到 access_token"


def launch_chrome(settings, use_proxy=False):
    """用系统 Chrome 打开小苏菲的浏览器会话，返回 subprocess.Popen。"""
    chrome = find_chrome(settings)
    if not chrome:
        _print("[错误] 找不到系统 Chrome。请安装 Chrome，或在 settings.json 里"
               " 设置 custom_browser_path。")
        sys.exit(2)

    url = settings.get("ms_url") or DEFAULT_URL
    w = int(settings.get("browser_width", 960))
    h = int(settings.get("browser_height", 540))

    cmd = [
        chrome,
        f"--user-data-dir={DATA_DIR}",
        f"--window-size={w},{h}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
    ]
    if use_proxy:
        port = settings.get("mitm_port", 10999)
        cmd.append(f"--proxy-server=http://127.0.0.1:{port}")

    cmd.append(url)
    _print(f"[信息] 启动浏览器: {chrome}")
    _print(f"[信息] 打开页面: {url}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        _print(f"[错误] 启动浏览器失败: {e}")
        sys.exit(1)
    return proc


def _run_pwsh(script_text):
    """用 -EncodedCommand 执行 PowerShell，避免中文路径编码问题。"""
    enc = base64.b64encode(script_text.encode("utf-16-le")).decode("ascii")
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            capture_output=True, timeout=45, text=True,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return None


def _chrome_main_pids():
    """返回所有使用本脚本 user-data-dir 的 chrome 主进程 PID(不含 --type= 子进程)。

    用 --user-data-dir 扫描而不是依赖 launch 时的 proc.pid：调度器内嵌执行时，
    Chrome 可能以 launcher 移交方式启动，导致 proc.pid 已退出而真实浏览器还活着。
    """
    marker = str(DATA_DIR)
    script = (
        "$m = '" + marker.replace("'", "''") + "';"
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" |"
        " Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $m + '*'))"
        " -and ($_.CommandLine -notlike '*--type=*') } |"
        " Select-Object -ExpandProperty ProcessId"
    )
    r = _run_pwsh(script)
    if not r or not r.stdout:
        return []
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def close_chrome(proc):
    """可靠关闭浏览器。Chrome 主进程无视 WM_CLOSE，须用 /F 兜底。

    先按 user-data-dir 找出真实浏览器进程(不依赖可能已失效的 proc.pid)，
    优雅关闭给落盘机会，随后 /F 强制结束残留。
    """
    pids = _chrome_main_pids()
    if proc.poll() is None and proc.pid not in pids:
        pids.append(proc.pid)
    if not pids:
        return

    _print(f"[信息] 关闭浏览器(进程 {pids})...")
    # 1) 优雅关闭(发 WM_CLOSE，部分子进程会先退出，给落盘机会)
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                       capture_output=True, timeout=20,
                       creationflags=_NO_WINDOW)
    time.sleep(2)
    # 2) 强制结束残留(Chrome 主进程一般需要 /F)
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=10,
                       creationflags=_NO_WINDOW)


def wait_for_login(timeout):
    """轮询 leveldb 判定登录，直到已登录/超时/用户回车。返回 True 表示已登录。"""
    _print("[信息] 等待登录；检测到已登录会自动退出。")

    quit_event = threading.Event()

    if sys.stdin.isatty():
        def _read_enter():
            try:
                input()
                quit_event.set()
            except EOFError:
                pass  # stdin 被关闭/重定向(如调度器)，不要误判为退出
            except Exception:
                pass
        threading.Thread(target=_read_enter, daemon=True).start()
        _print("[信息] 判定不准时，也可在此按回车手动确认退出。")

    deadline = time.time() + timeout if timeout > 0 else None
    while True:
        logged_in, detail = _detect_login_from_disk()
        if logged_in:
            _print(f"[信息] {detail}。")
            return True
        if quit_event.is_set():
            _print("[信息] 收到手动退出指令。")
            return False
        if deadline and time.time() >= deadline:
            _print(f"[警告] 等待登录超时({timeout} 秒)，仍未登录。")
            return False
        time.sleep(1)


def _open_browser(args, settings, mode):
    """--login / --open 共用：开浏览器，按 -q/--delay/--timeout 决定是否自动退出。"""
    proc = launch_chrome(settings, use_proxy=args.proxy)

    # 只要指定了 -q 或 --delay，就进入“打开后自动退出”流程
    if args.quiet or args.delay is not None:
        if args.delay is not None:
            # 固定停留 N 秒后退出(确定性，不依赖登录判定)
            dwell = args.delay
            _print(f"[信息] 停留 {dwell:g} 秒后退出...")
            try:
                time.sleep(dwell)
            except KeyboardInterrupt:
                pass
            logged_in, detail = _detect_login_from_disk()
            _print(f"[信息] 停留结束。{detail}")
        else:
            # 基于登录判定，可选 --timeout 上限
            logged_in = wait_for_login(args.timeout)

        _print("[信息] 关闭浏览器并保存会话...")
        close_chrome(proc)
        _print("[完成] 脚本退出。")
        sys.exit(0 if logged_in else 1)

    # 非 -q：保持浏览器打开，关闭窗口或 Ctrl+C 退出
    label = "登录" if mode == "login" else "进入游戏"
    _print(f"[信息] 浏览器保持打开({label})。关闭浏览器窗口即退出本脚本。")
    try:
        while proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        close_chrome(proc)


def cmd_app():
    """启动主程序 suphx.exe(其自带图形界面与 AI 自动打牌逻辑)。"""
    exe = APP_EXE if APP_EXE.exists() else LAUNCHER_EXE
    if not exe.exists():
        _print(f"[错误] 找不到主程序: {exe}")
        sys.exit(1)
    _print(f"[信息] 启动主程序 {exe.name}")
    subprocess.Popen([str(exe)], cwd=str(INTERNAL))


# ---- 入口 -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="小苏菲命令行启动器(纯标准库，登录持久化，与 exe 共享会话)")
    ap.add_argument("--login", action="store_true", help="打开浏览器并停留登录")
    ap.add_argument("--open", action="store_true", help="直接进入游戏(需已登录)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="配合 --login/--open: 检测到登录后自动退出")
    ap.add_argument("--app", action="store_true", help="启动主程序 suphx.exe")
    ap.add_argument("--proxy", action="store_true",
                    help="浏览器走主程序的 mitm 代理(需 mitm 已在运行)")
    ap.add_argument("--timeout", type=int, default=0, metavar="秒",
                    help="-q 模式下等待登录的最大秒数(0=一直等, 默认)")
    ap.add_argument("--delay", type=float, default=None, metavar="秒",
                    help="打开后固定停留 N 秒再退出(配合 -q；如 --open --delay 30 -q)")
    args = ap.parse_args()

    # 直接调用本脚本(不带任何参数)时，默认执行 --open --delay 30 -q
    if len(sys.argv) == 1:
        args.open = True
        args.delay = 30.0
        args.quiet = True

    settings = load_settings()

    if args.login:
        _open_browser(args, settings, mode="login")
    elif args.open:
        _open_browser(args, settings, mode="open")
    elif args.app:
        cmd_app()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
