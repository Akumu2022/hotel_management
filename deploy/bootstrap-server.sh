#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04 / 24.04 server (run as root, once):
#   bash deploy/bootstrap-server.sh
# Installs Docker, opens only SSH + web ports in the firewall, blocks password guessing on SSH,
# adds a little swap (the web app is built on the server) and turns on automatic security updates.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root:  sudo bash deploy/bootstrap-server.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get -y install ca-certificates curl git ufw fail2ban unattended-upgrades

# Docker (official installer)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# Firewall: SSH, HTTP (for certificates), HTTPS. Everything else is closed.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# Repeated wrong SSH passwords get that address blocked.
systemctl enable --now fail2ban

# 2 GB swap so building the web app cannot run a small server out of memory.
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Automatic security updates.
dpkg-reconfigure -f noninteractive unattended-upgrades

# Where backups go.
mkdir -p /var/backups/chakula
chmod 700 /var/backups/chakula

echo
echo "Server ready. Next: follow deploy/DEPLOY.md from step 3."
