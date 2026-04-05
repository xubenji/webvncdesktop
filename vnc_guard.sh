#!/bin/bash
# VNC 端口守卫：添加 iptables DROP 规则屏蔽 VNC 端口
PORTS=(5901 6901)

for port in "${PORTS[@]}"; do
    sudo iptables -C INPUT -p tcp -m tcp --dport "$port" -j DROP 2>/dev/null || \
    sudo iptables -A INPUT -p tcp -m tcp --dport "$port" -j DROP
done
echo "[vnc_guard] 端口已屏蔽: ${PORTS[*]}"
