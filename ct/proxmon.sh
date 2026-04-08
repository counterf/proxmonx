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
# NOTE: build_container is NOT used — it hardcodes the install script URL to
# community-scripts/ProxmoxVE with no override. We use create_lxc_container
# directly (a standalone function that handles storage, template, and pct create)
# then invoke our own install script via pct exec.

# Container ID is set by the wizard via CT_ID
CTID="${CT_ID}"
export CTID

# OS/disk exports required by create_lxc_container
export PCT_OSTYPE="$var_os"
export PCT_OSVERSION="$var_version"
export PCT_DISK_SIZE="${DISK_SIZE:-$var_disk}"

# Build features string — nesting required for systemd inside the container
FEATURES="nesting=1"
[[ "${CT_TYPE:-1}" == "1" ]] && FEATURES="${FEATURES},keyctl=1"

# Build PCT_OPTIONS — create_lxc_container appends -rootfs automatically
export PCT_OPTIONS="  -features ${FEATURES}
  -hostname ${HN:-proxmon}
  -net0 name=eth0,bridge=${BRG:-vmbr0},ip=${NET:-dhcp}
  -onboot 1
  -cores ${CORE_COUNT:-$var_cpu}
  -memory ${RAM_SIZE:-$var_ram}
  -unprivileged ${CT_TYPE:-1}"

[[ -n "${TAGS:-}" ]] && PCT_OPTIONS="${PCT_OPTIONS}
  -tags ${TAGS}"

# create_lxc_container handles: storage selection, template download, pct create + retry logic
msg_info "Creating LXC Container"
create_lxc_container || exit $?
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
# The install script must run inside the container WITHOUT host-side shell
# expansion. Using 'bash -c "$(curl ...)"' would cause the host shell to expand
# every $VAR and $(cmd) in the fetched script before passing it to the container,
# breaking variable assignments and command substitutions that must run inside.
# Piping via 'bash -s' sends the script verbatim through stdin, avoiding this.
curl -fsSL https://raw.githubusercontent.com/counterf/proxmonx/main/install/proxmon-install.sh \
  | pct exec "$CTID" -- bash -s
msg_ok "Completed Install Script"

description

msg_ok "Completed successfully!\n"
echo -e "${CREATING}${GN}${APP} setup has been successfully initialized!${CL}"
echo -e "${INFO}${YW} Access it using the following URL:${CL}"
echo -e "${TAB}${GATEWAY}${BGN}http://${IP}:3000${CL}"
