#!/usr/bin/env bash
# Copyright (c) 2021-2026 community-scripts ORG
# Author: Alysson Silva
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://github.com/counterf/proxmonx

# Fetch install.func if not already provided via environment.
# Standard community-scripts path sets FUNCTIONS_FILE_PATH before lxc-attach;
# our custom path (ct/proxmon.sh) does not — be self-sufficient.
if [[ -z "${FUNCTIONS_FILE_PATH:-}" ]]; then
  FUNCTIONS_FILE_PATH="$(curl -fsSL \
    https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/install.func)"
fi
# shellcheck disable=SC1090
source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

msg_info "Installing Dependencies"
# Minimal Debian 13 template ships almost no userland — install all required tooling.
# Debian 13 ships Python 3.13 as default; python3/python3-venv satisfy >=3.12 requirement.
$STD apt-get install -y curl ca-certificates python3 python3-venv
msg_ok "Installed Dependencies"

msg_info "Downloading proxmon Release"
fetch_and_deploy_gh_release \
  "proxmon" "counterf/proxmonx" "prebuild" "latest" \
  "/opt/proxmon/lib" "proxmon-*-linux.tar.gz"
msg_ok "Downloaded proxmon Release"

msg_info "Setting Up Directories"
mkdir -p /opt/proxmon/{data,logs}
msg_ok "Set Up Directories"

msg_info "Creating Virtual Environment"
python3 -m venv /opt/proxmon/.venv
# .venv lives at /opt/proxmon/.venv — outside lib/ so CLEAN_INSTALL wipes don't destroy it
/opt/proxmon/.venv/bin/pip install -r /opt/proxmon/lib/requirements.txt --no-cache-dir -q
msg_ok "Created Virtual Environment"

msg_info "Creating System User"
useradd -r -s /usr/sbin/nologin --home-dir /opt/proxmon proxmon
chown -R proxmon:proxmon /opt/proxmon
msg_ok "Created System User"

msg_info "Creating Service"
cat <<'EOF' >/etc/systemd/system/proxmon.service
[Unit]
Description=proxmon - Proxmox monitoring dashboard
After=network.target
StartLimitBurst=5
StartLimitIntervalSec=60

[Service]
Type=simple
User=proxmon
WorkingDirectory=/opt/proxmon/lib
Environment=CONFIG_DB_PATH=/opt/proxmon/data/proxmon.db
Environment=PORT=3000
ExecStart=/opt/proxmon/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3000
Restart=on-failure
RestartSec=5s
StandardOutput=append:/opt/proxmon/logs/proxmon.log
StandardError=append:/opt/proxmon/logs/proxmon.log

[Install]
WantedBy=multi-user.target
EOF
systemctl enable -q --now proxmon
msg_ok "Created Service"

msg_info "Configuring Log Rotation"
cat <<'EOF' >/etc/logrotate.d/proxmon
/opt/proxmon/logs/proxmon.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
EOF
msg_ok "Configured Log Rotation"

motd_ssh
customize
cleanup_lxc
