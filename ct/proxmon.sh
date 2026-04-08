#!/usr/bin/env bash
# Copyright (c) 2021-2026 community-scripts ORG
# Author: Alysson Silva
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://github.com/counterf/proxmonx

source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)

APP="proxmon"
var_tags="${var_tags:-monitoring}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_unprivileged="${var_unprivileged:-1}"
# Use minimal Debian 13 template (fewer pre-installed packages, smaller footprint)
TEMPLATE_FILTER="${TEMPLATE_FILTER:-minimal}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
  # NOTE: this function runs INSIDE the container when the user executes /usr/bin/update.
  # ct/proxmon.sh is re-downloaded and re-run inside the container by the update wrapper;
  # build.func's start() detects the existing installation and routes here.
  header_info
  check_container_storage
  check_container_resources
  if [[ ! -d /opt/proxmon/lib ]]; then
    msg_error "No ${APP} Installation Found!"
    exit
  fi

  msg_info "Stopping Service"
  systemctl stop proxmon
  msg_ok "Stopped Service"

  CLEAN_INSTALL=1 fetch_and_deploy_gh_release \
    "proxmon" "counterf/proxmonx" "prebuild" "latest" \
    "/opt/proxmon/lib" "proxmon-*-linux.tar.gz"

  msg_info "Syncing Python Dependencies"
  /opt/proxmon/.venv/bin/pip install -r /opt/proxmon/lib/requirements.txt --no-cache-dir -q
  msg_ok "Synced Python Dependencies"

  msg_info "Starting Service"
  systemctl start proxmon
  msg_ok "Started Service"

  msg_info "Verifying Service Health"
  if curl --retry 5 --retry-delay 2 -sf http://localhost:3000/health >/dev/null 2>&1; then
    msg_ok "Service is healthy"
  else
    msg_error "Service did not respond on :3000 after update — check: tail -f /opt/proxmon/logs/proxmon.log"
  fi

  msg_ok "Updated successfully!"
  exit
}

start
# NOTE: build_container is NOT used — it hardcodes the install script URL to
# community-scripts/ProxmoxVE with no override. We replicate the essential
# pct create → pct start → lxc-attach sequence manually to invoke our own script.

select_storage "container"
select_template

CTID=$(get_valid_container_id)

msg_info "Creating LXC Container"
pct create "$CTID" "$TEMPLATE_PATH" \
  -hostname "${HN:-proxmon}" \
  -cores "${CORE_COUNT:-$var_cpu}" \
  -memory "${RAM_SIZE:-$var_ram}" \
  -rootfs "${CONTAINER_STORAGE}:${DISK_SIZE:-$var_disk}" \
  -net0 "name=eth0,bridge=${BRG:-vmbr0},ip=dhcp" \
  -unprivileged "$CT_TYPE" \
  -features "keyctl=1,nesting=1" \
  -onboot 1
msg_ok "Created LXC Container ($CTID)"

msg_info "Starting LXC Container"
pct start "$CTID"
# Poll for network readiness instead of a fixed sleep (15 attempts × 2s = 30s max)
for i in $(seq 1 15); do
  pct exec "$CTID" -- ping -c1 -W1 8.8.8.8 &>/dev/null && break
  sleep 2
done
msg_ok "Started LXC Container"

msg_info "Running Install Script"
# lxc-attach does NOT forward host environment variables — FUNCTIONS_FILE_PATH must
# be fetched inside the container. The install script handles this itself (self-fetches
# install.func if FUNCTIONS_FILE_PATH is absent).
lxc-attach -n "$CTID" -- bash -c \
  "$(curl -fsSL https://raw.githubusercontent.com/counterf/proxmonx/main/install/proxmon-install.sh)"
msg_ok "Completed Install Script"

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
description

msg_ok "Completed successfully!\n"
echo -e "${CREATING}${GN}${APP} setup has been successfully initialized!${CL}"
echo -e "${INFO}${YW} Access it using the following URL:${CL}"
echo -e "${TAB}${GATEWAY}${BGN}http://${IP}:3000${CL}"
