#!/usr/bin/env bash
# Copyright (c) 2021-2026 community-scripts ORG
# Author: Alysson Silva
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://github.com/counterf/proxmonx

# Forked build.func: identical to community-scripts except the install script
# URL points to counterf/proxmonx instead of community-scripts/ProxmoxVE.
source <(curl -fsSL https://raw.githubusercontent.com/counterf/proxmonx/main/misc/build.func)

APP="proxmon"
var_tags="${var_tags:-monitoring}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-1024}"
var_disk="${var_disk:-4}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_unprivileged="${var_unprivileged:-1}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
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
build_container
description

msg_ok "Completed successfully!\n"
echo -e "${CREATING}${GN}${APP} setup has been successfully initialized!${CL}"
echo -e "${INFO}${YW} Access it using the following URL:${CL}"
echo -e "${TAB}${GATEWAY}${BGN}http://${IP}:3000${CL}"
