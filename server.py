#!/usr/bin/env python3
"""only_init_desktop — Web 管理面板

轻量 Flask 服务，提供 VNC 桌面的放行/关闭控制。
"""

import hmac
import os
import subprocess
import threading
import time
from datetime import timedelta
from functools import wraps

import yaml
from flask import Flask, jsonify, request, send_from_directory, session

# ──────────────────────────── 配置 ────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

_cfg = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        _cfg = yaml.safe_load(f) or {}

VNC_USER    = _cfg.get("vnc_user", "user1")
VNC_PASS    = _cfg.get("vnc_pass", "")
VNC_PORT    = int(_cfg.get("vnc_port", 5901))
NOVNC_PORT  = int(_cfg.get("novnc_port", 6901))
TERM_PORT   = int(_cfg.get("term_port", 7681))
DISPLAY_ID  = int(_cfg.get("display_id", 1))
WEBUI_USER  = _cfg.get("webui_user")
WEBUI_PASS  = _cfg.get("webui_pass")

GUARD_SCRIPT   = os.path.join(SCRIPT_DIR, "vnc_guard.sh")
UNGUARD_SCRIPT = os.path.join(SCRIPT_DIR, "vnc_unguard.sh")

RESTORE_DELAY  = 900   # 15 分钟
X11VNC_TIMEOUT = 900   # x11vnc 空闲超时

WEB_PORT = int(os.environ.get("PORT", 8080))

# ──────────────────────────── Flask ────────────────────────────

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"]                = os.environ.get("SECRET_KEY", "only-init-desktop-secret")
app.config["SESSION_COOKIE_HTTPONLY"]   = True
app.config["SESSION_COOKIE_SAMESITE"]   = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# ── 自动恢复定时器 ──
_restore_timer: threading.Timer | None = None
_timer_lock = threading.Lock()



# ──────────────────────────── 安全头 ────────────────────────────

@app.after_request
def apply_security_headers(response):
    response.headers.pop("Server", None)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["Referrer-Policy"]        = "no-referrer"
    return response


# ──────────────────────────── 认证 ────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/api/me")
def api_me():
    return jsonify({"logged_in": bool(session.get("logged_in"))})


@app.route("/api/auth_check")
def api_auth_check():
    """供 nginx auth_request 调用，200=已登录，401=未登录"""
    if session.get("logged_in"):
        return "", 200
    return "", 401


@app.route("/api/login", methods=["POST"])
def api_login():
    body     = request.get_json(force=True) or {}
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))

    if not WEBUI_USER or not WEBUI_PASS:
        return jsonify({"error": "凭据未配置，请先运行 install.sh"}), 403

    ok = (
        hmac.compare_digest(username, WEBUI_USER)
        and hmac.compare_digest(password, WEBUI_PASS)
    )
    if ok:
        session.permanent = True
        session["logged_in"] = True
        return jsonify({"success": True})
    return jsonify({"error": "用户名或密码错误"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


# ──────────────────────────── 静态文件 ────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ──────────────────────────── VNC API ────────────────────────────

@app.route("/api/vnc_open", methods=["POST"])
@require_auth
def api_vnc_open():
    """放行 VNC 端口 + 启动 x11vnc，15 分钟后自动恢复"""
    global _restore_timer
    lines = []

    # 1. 杀已有 x11vnc
    subprocess.run(
        f"pkill -f 'x11vnc.*:{DISPLAY_ID}' || true",
        shell=True, capture_output=True,
    )

    # 2. 启动 x11vnc
    x11vnc_cmd = (
        f"x11vnc -display :{DISPLAY_ID} -rfbport {VNC_PORT} "
        f"-forever -shared -bg -nopw -timeout {X11VNC_TIMEOUT}"
    )
    proc = subprocess.run(x11vnc_cmd, shell=True, capture_output=True, text=True)
    if proc.returncode == 0:
        lines.append(f"x11vnc 已启动: display=:{DISPLAY_ID} port={VNC_PORT}")
    else:
        lines.append(f"x11vnc 启动失败: {proc.stderr.strip()}")

    # 3. 放行 iptables
    proc2 = subprocess.run(f"bash {UNGUARD_SCRIPT}", shell=True, capture_output=True, text=True)
    lines.append(proc2.stdout.strip())

    # 4. 取消旧定时器，设置新的 15 分钟自动恢复
    with _timer_lock:
        if _restore_timer is not None:
            _restore_timer.cancel()
        _restore_timer = threading.Timer(RESTORE_DELAY, _auto_restore)
        _restore_timer.daemon = True
        _restore_timer.start()

    lines.append(f"已设置 {RESTORE_DELAY // 60} 分钟后自动恢复屏蔽")
    return jsonify({"success": True, "message": "\n".join(lines)})


@app.route("/api/vnc_close", methods=["POST"])
@require_auth
def api_vnc_close():
    """立即关闭 VNC 端口 + 杀 x11vnc"""
    global _restore_timer

    # 取消定时器
    with _timer_lock:
        if _restore_timer is not None:
            _restore_timer.cancel()
            _restore_timer = None

    # 杀 x11vnc
    subprocess.run(
        f"pkill -f 'x11vnc.*:{DISPLAY_ID}' || true",
        shell=True, capture_output=True,
    )

    # 屏蔽端口
    proc = subprocess.run(f"bash {GUARD_SCRIPT}", shell=True, capture_output=True, text=True)
    return jsonify({"success": True, "message": proc.stdout.strip()})


@app.route("/api/vnc_status")
@require_auth
def api_vnc_status():
    """查询 VNC 当前状态"""
    # 检查 x11vnc 是否在运行
    result = subprocess.run(
        f"pgrep -f 'x11vnc.*:{DISPLAY_ID}'",
        shell=True, capture_output=True, text=True,
    )
    x11vnc_running = result.returncode == 0

    # 检查端口是否被屏蔽
    result2 = subprocess.run(
        f"sudo iptables -C INPUT -p tcp -m tcp --dport {NOVNC_PORT} -j DROP 2>/dev/null",
        shell=True, capture_output=True,
    )
    port_blocked = result2.returncode == 0

    with _timer_lock:
        timer_active = _restore_timer is not None and _restore_timer.is_alive()

    return jsonify({
        "x11vnc_running": x11vnc_running,
        "port_blocked": port_blocked,
        "auto_close_pending": timer_active,
    })


@app.route("/api/server_info")
@require_auth
def api_server_info():
    """返回 noVNC 连接信息"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    novnc_url = f"http://{ip}:{NOVNC_PORT}/vnc.html?autoconnect=true&password={VNC_PASS}"
    term_url = f"http://{ip}:{WEB_PORT}/terminal/"
    return jsonify({
        "ip": ip,
        "novnc_port": NOVNC_PORT,
        "novnc_url": novnc_url,
        "term_url": term_url,
    })


def _auto_restore():
    """定时回调：杀 x11vnc + 恢复屏蔽"""
    subprocess.run(
        f"pkill -f 'x11vnc.*:{DISPLAY_ID}' || true",
        shell=True, capture_output=True,
    )
    subprocess.run(f"bash {GUARD_SCRIPT}", shell=True, capture_output=True)
    print(f"[auto_restore] VNC 已自动关闭（{RESTORE_DELAY // 60} 分钟超时）")


# ──────────────────────────── ttyd 常驻 ────────────────────────────

def _ensure_ttyd():
    """确保 ttyd 在运行，未运行则启动"""
    result = subprocess.run(["pgrep", "-x", "ttyd"], capture_output=True)
    if result.returncode != 0:
        subprocess.Popen(
            f"ttyd -i 127.0.0.1 -p {TERM_PORT} -W -t fontSize=16 -t 'theme={{\"background\":\"#0f1117\"}}' login",
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[ttyd] 已启动常驻终端: port={TERM_PORT}")
    else:
        print(f"[ttyd] 终端已在运行: port={TERM_PORT}")


# ──────────────────────────── 入口 ────────────────────────────

if __name__ == "__main__":
    _ensure_ttyd()
    print(f"VNC Desktop Manager -> http://0.0.0.0:{WEB_PORT}")
    if WEBUI_USER:
        print(f"登录用户名: {WEBUI_USER}")
    else:
        print("警告: 凭据未配置，所有登录将被拒绝")
    app.run(host="127.0.0.1", port=8081, debug=False)
