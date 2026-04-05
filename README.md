# Only Init Desktop

纯净 Ubuntu 22.04 一键安装 VNC 桌面环境 + Web 管理面板。

## 文件结构

```
only_init_desktop/
├── install.sh          # 一键安装入口（root 执行）
├── server.py           # Web 管理面板（Flask）
├── vnc_guard.sh        # iptables 屏蔽 VNC 端口
├── vnc_unguard.sh      # iptables 放行 VNC 端口
└── static/
    └── index.html      # Web 前端
```

## 安装

```bash
sudo bash install.sh
```

交互式输入：
- VNC / 系统用户密码
- Web 管理面板用户名
- Web 管理面板密码

安装内容：
- 桌面环境：xfce4 + dbus + xvfb + x11vnc
- VNC 服务：tightvncserver + noVNC + websockify
- 浏览器：firefox-esr
- 系统用户：user1（自动创建）
- 2GB swap（小内存服务器防 OOM）

## 使用

安装完成后访问 `http://<服务器IP>:8080`，登录后：

- **打开 VNC 桌面** — 放行端口 + 启动 x11vnc，自动在新标签页打开 noVNC 网页桌面
- **关闭** — 立即屏蔽端口 + 杀掉 x11vnc

## 安全机制

- 默认屏蔽 VNC 端口（5901/6901），外部无法直接访问
- 点击"打开 VNC 桌面"临时放行，**15 分钟后自动恢复屏蔽**
- Web 面板需登录认证，session 8 小时有效
- user1 仅授予免密 sudo iptables 权限

## 端口

| 端口 | 用途 |
|------|------|
| 8080 | Web 管理面板 |
| 5901 | VNC 端口（默认屏蔽） |
| 6901 | noVNC 网页访问（默认屏蔽） |

## 手动管理

```bash
# 手动启动 Web 管理面板
python3 server.py

# 手动屏蔽/放行 VNC 端口
bash vnc_guard.sh
bash vnc_unguard.sh
```
