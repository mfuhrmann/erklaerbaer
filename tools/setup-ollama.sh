#!/usr/bin/env bash
# Install the Vulkan build of Ollama and run it as a system service.
# Run as root: sudo bash tools/setup-ollama.sh
set -euo pipefail

pacman -S --needed ollama-vulkan

mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_IGPU_ENABLE=1"
Environment="OLLAMA_CONTEXT_LENGTH=32768"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
EOF

systemctl daemon-reload
systemctl enable --now ollama
systemctl restart ollama
systemctl --no-pager status ollama | head -5
