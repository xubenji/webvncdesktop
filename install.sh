#!/bin/bash
set -euo pipefail

# =============================================
#  only_init_desktop — 一键安装 VNC 桌面 + Web 管理面板
#  适用于纯净 Ubuntu 22.04 系统
# =============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VNC_USER="user1"
DISPLAY_ID=1
GEOMETRY="1440x900"
DEPTH=24
VNC_PORT=$((5900 + DISPLAY_ID))
NOVNC_PORT=$((VNC_PORT + 1000))   # 6901
TERM_PORT=7681
WEB_PORT=8080

die() { echo "[ERROR] $*" >&2; exit 1; }
info() { echo "[INFO] $*"; }

[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "请以 root 执行: sudo bash $0"

echo ""
echo "========================================="
echo "   VNC 桌面一键安装"
echo "========================================="
echo ""

# ── 收集用户输入 ──

read -rp "[?] 请输入 VNC / 系统用户密码: " VNC_PASS
while [ -z "$VNC_PASS" ]; do
    echo "[!] 密码不能为空"; read -rp "[?] 请输入 VNC / 系统用户密码: " VNC_PASS
done

read -rp "[?] 请输入 Web 管理面板用户名: " WEBUI_USER
while [ -z "$WEBUI_USER" ]; do
    echo "[!] 不能为空"; read -rp "[?] 请输入 Web 管理面板用户名: " WEBUI_USER
done

read -rp "[?] 请输入 Web 管理面板密码: " WEBUI_PASS
while [ -z "$WEBUI_PASS" ]; do
    echo "[!] 不能为空"; read -rp "[?] 请输入 Web 管理面板密码: " WEBUI_PASS
done

echo ""
info "开始安装..."

# ── 1. 添加 swap（小内存服务器防 OOM）──

if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile > /dev/null 2>&1
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    info "创建 2GB swap"
else
    info "swap 已存在，跳过"
fi

# ── 2. 安装系统包 ──

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# 桌面环境（XFCE4 完整桌面）
apt-get install -y \
    xfce4 xfce4-terminal dbus-x11 x11-xserver-utils xauth \
    xvfb x11vnc > /dev/null 2>&1
info "安装桌面环境（xfce4 + xvfb + x11vnc）"

# TightVNC
apt-get install -y tightvncserver > /dev/null 2>&1
info "安装 tightvncserver"

# noVNC + websockify
apt-get install -y novnc python3-websockify > /dev/null 2>&1
info "安装 noVNC + websockify"

# Firefox ESR
add-apt-repository ppa:mozillateam/ppa -y > /dev/null 2>&1
apt-get update -qq > /dev/null 2>&1
apt-get install -y firefox-esr > /dev/null 2>&1
info "安装 firefox-esr"

# ttyd（Web 终端）
if ! command -v ttyd &>/dev/null; then
    wget -qO /usr/local/bin/ttyd \
        https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.x86_64
    chmod +x /usr/local/bin/ttyd
    info "安装 ttyd"
else
    info "ttyd 已存在，跳过"
fi

# Python 依赖（Web 管理面板）
apt-get install -y python3-pip > /dev/null 2>&1
pip3 install flask pyyaml > /dev/null 2>&1
info "安装 Python 依赖"

# ── 3. 创建用户 ──

if id "$VNC_USER" >/dev/null 2>&1; then
    info "用户 $VNC_USER 已存在"
else
    adduser --gecos "" --disabled-password "$VNC_USER" > /dev/null
    info "创建用户 $VNC_USER"
fi
echo "$VNC_USER:$VNC_PASS" | chpasswd
usermod -aG sudo "$VNC_USER"
info "已将 $VNC_USER 加入 sudo 组"

# ── 4. 配置 VNC 桌面 ──

VNC_HOME="$(eval echo "~$VNC_USER")"
su - "$VNC_USER" -c "mkdir -p '$VNC_HOME/.vnc'"

# xstartup
cat > "$VNC_HOME/.vnc/xstartup" <<'XSTARTUP'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

export XDG_RUNTIME_DIR="$HOME/.run"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

xrdb "$HOME/.Xresources" 2>/dev/null || true
xsetroot -solid grey

exec dbus-run-session startxfce4
XSTARTUP
chmod 755 "$VNC_HOME/.vnc/xstartup"
chown "$VNC_USER:$VNC_USER" "$VNC_HOME/.vnc/xstartup"

# VNC 密码
su - "$VNC_USER" -c "printf '%s\n' '$VNC_PASS' | vncpasswd -f > '$VNC_HOME/.vnc/passwd'"
su - "$VNC_USER" -c "chmod 600 '$VNC_HOME/.vnc/passwd'"
info "配置 VNC xstartup + 密码"

# ── 5. 启动 vncserver ──

su - "$VNC_USER" -c "vncserver -kill :$DISPLAY_ID > /dev/null 2>&1 || true"
su - "$VNC_USER" -c "vncserver :$DISPLAY_ID -geometry $GEOMETRY -depth $DEPTH"
info "启动 vncserver :$DISPLAY_ID (端口 $VNC_PORT)"

# ── 6. 启动 websockify（noVNC）──

# 先杀已有的
pkill -f "websockify.*$NOVNC_PORT" 2>/dev/null || true
sleep 1

NOVNC_DIR="/usr/share/novnc"
websockify --web "$NOVNC_DIR" --daemon "$NOVNC_PORT" "localhost:$VNC_PORT"
info "启动 noVNC websockify :$NOVNC_PORT -> :$VNC_PORT"

# ── 7. 授予用户 sudo iptables 权限 ──

SUDOERS_FILE="/etc/sudoers.d/${VNC_USER}-iptables"
echo "$VNC_USER ALL=(root) NOPASSWD: $(which iptables)" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"
info "授予 $VNC_USER 免密 sudo iptables"

# ── 8. 屏蔽 VNC 端口（默认安全状态）──

bash "$SCRIPT_DIR/vnc_guard.sh"
info "VNC 端口已屏蔽（默认安全）"

# ── 9. 写入配置文件 ──

cat > "$SCRIPT_DIR/config.yaml" <<EOF
vnc_user: "$VNC_USER"
vnc_pass: "$VNC_PASS"
vnc_port: $VNC_PORT
novnc_port: $NOVNC_PORT
term_port: $TERM_PORT
display_id: $DISPLAY_ID
webui_user: "$WEBUI_USER"
webui_pass: "$WEBUI_PASS"
EOF
info "写入 config.yaml"

# ── 10. 启动 Web 管理面板 ──

pkill -f "python3.*server.py" 2>/dev/null || true
sleep 1
nohup python3 "$SCRIPT_DIR/server.py" > "$SCRIPT_DIR/server.log" 2>&1 &
info "启动 Web 管理面板（端口 $WEB_PORT）"

# ── 完成 ──

SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================="
echo "   安装完成"
echo ""
echo "   Web 管理面板: http://${SERVER_IP}:${WEB_PORT}"
echo "   用户名: $WEBUI_USER"
echo "   密  码: $WEBUI_PASS"
echo ""
echo "   noVNC 地址:   http://${SERVER_IP}:${NOVNC_PORT}/vnc.html"
echo "   （端口默认屏蔽，需通过 Web 面板放行）"
echo ""
echo "   Web 终端:     http://${SERVER_IP}:${TERM_PORT}（常驻）"
echo ""
echo "   VNC 用户: $VNC_USER"
echo "   VNC 密码: $VNC_PASS"
echo "========================================="
