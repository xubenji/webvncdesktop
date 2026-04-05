#!/bin/bash
# VNC 端口放行：删除 iptables DROP 规则
PORTS=(5901 6901)

for port in "${PORTS[@]}"; do
    sudo iptables -D INPUT -p tcp -m tcp --dport "$port" -j DROP 2>/dev/null
done
echo "[vnc_guard] 端口已放行: ${PORTS[*]}"
