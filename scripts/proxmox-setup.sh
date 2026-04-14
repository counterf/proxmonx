#!/usr/bin/env bash
#
# proxmox-setup.sh — Configure minimal-privilege access for Proxmon
#
# Run on a Proxmox host as root. Creates:
#   - PVE role, user, API token with least-privilege permissions
#   - System user with sudoers for pct exec (SSH access)
#   - Ed25519 SSH key pair (private key displayed for pasting into Proxmon)
#
# Usage:
#   ./proxmox-setup.sh              # generate key pair (recommended)
#   ./proxmox-setup.sh --password   # use password instead of key
#
set -euo pipefail

PVE_ROLE="ProxmonRole"
PVE_PRIVS="VM.Audit,VM.PowerMgmt,VM.Snapshot,VM.Backup,Datastore.Audit,Sys.Audit"
PVE_USER="proxmon@pve"
PVE_TOKEN_NAME="monitoring"
PVE_TOKEN_ID="${PVE_USER}!${PVE_TOKEN_NAME}"
SSH_USER="proxmon"
SUDOERS_FILE="/etc/sudoers.d/proxmon"

# Track changes
CHANGES=()
SKIPPED=()
TOKEN_SECRET=""
SSH_AUTH_METHOD=""
SSH_PASSWORD=""
SSH_PRIVATE_KEY=""

log_created() { CHANGES+=("[CREATED] $1"); }
log_updated() { CHANGES+=("[UPDATED] $1"); }
log_skipped() { SKIPPED+=("[SKIPPED] $1"); }

info()  { echo "  -> $*"; }
error() { echo "ERROR: $*" >&2; exit 1; }

# --- Preflight checks ---

[[ $EUID -eq 0 ]] || error "Must run as root"
command -v pveum >/dev/null 2>&1 || error "'pveum' not found — is this a Proxmox host?"
command -v pct  >/dev/null 2>&1 || error "'pct' not found — is this a Proxmox host?"

# --- Parse arguments ---

MODE="keygen"   # keygen (default) | password

while [[ $# -gt 0 ]]; do
    case "$1" in
        --password)
            MODE="password"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--password]"
            echo ""
            echo "  (default)    Generate an Ed25519 SSH key pair (recommended)"
            echo "  --password   Generate a random password instead"
            exit 0
            ;;
        *)
            error "Unknown argument: $1"
            ;;
    esac
done

echo ""
echo "=== Proxmon Proxmox Setup ==="
echo ""

# -----------------------------------------------------------------------
# API SETUP
# -----------------------------------------------------------------------

echo "--- API Setup ---"
echo ""

# 1. Role
if pveum role list --output-format json 2>/dev/null | grep -q "\"$PVE_ROLE\""; then
    log_skipped "PVE role '$PVE_ROLE' (already exists)"
    info "Role '$PVE_ROLE' already exists"
else
    pveum role add "$PVE_ROLE" -privs "$PVE_PRIVS"
    log_created "PVE role '$PVE_ROLE' with privs: $PVE_PRIVS"
    info "Created role '$PVE_ROLE'"
fi

# 2. User
if pveum user list --output-format json 2>/dev/null | grep -q "\"$PVE_USER\""; then
    log_skipped "PVE user '$PVE_USER' (already exists)"
    info "User '$PVE_USER' already exists"
else
    pveum user add "$PVE_USER"
    log_created "PVE user '$PVE_USER'"
    info "Created user '$PVE_USER'"
fi

# 3. API Token
if pveum user token list "$PVE_USER" --output-format json 2>/dev/null | grep -q "\"$PVE_TOKEN_NAME\""; then
    log_skipped "API token '$PVE_TOKEN_ID' (already exists)"
    info "Token '$PVE_TOKEN_ID' already exists (secret not re-displayed)"
    TOKEN_SECRET="(existing — not re-displayed)"
else
    TOKEN_OUTPUT=$(pveum user token add "$PVE_USER" "$PVE_TOKEN_NAME" -privsep 0 --output-format json 2>&1)
    TOKEN_SECRET=$(echo "$TOKEN_OUTPUT" | grep -oP '"value"\s*:\s*"\K[^"]+' || echo "$TOKEN_OUTPUT")
    log_created "API token '$PVE_TOKEN_ID'"
    info "Created token '$PVE_TOKEN_ID'"
fi

# 4. ACL
pveum acl modify / -user "$PVE_USER" -role "$PVE_ROLE"
log_updated "ACL: $PVE_USER -> $PVE_ROLE on /"
info "Assigned role '$PVE_ROLE' to '$PVE_USER' on /"

echo ""

# -----------------------------------------------------------------------
# SSH SETUP
# -----------------------------------------------------------------------

echo "--- SSH Setup ---"
echo ""

# 1. System user
if id "$SSH_USER" &>/dev/null; then
    log_skipped "System user '$SSH_USER' (already exists)"
    info "System user '$SSH_USER' already exists"
else
    useradd -r -m -s /bin/bash "$SSH_USER"
    log_created "System user '$SSH_USER'"
    info "Created system user '$SSH_USER'"
fi

# 2. Sudoers
SUDOERS_LINE="$SSH_USER ALL=(root) NOPASSWD: /usr/sbin/pct exec *"
if [[ -f "$SUDOERS_FILE" ]] && grep -qF "$SUDOERS_LINE" "$SUDOERS_FILE"; then
    log_skipped "$SUDOERS_FILE (already configured)"
    info "Sudoers already configured"
else
    echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    log_created "$SUDOERS_FILE"
    info "Created sudoers rule: $SUDOERS_LINE"
fi

# 3. SSH auth
SSH_DIR="$(eval echo ~"$SSH_USER")/.ssh"

if [[ "$MODE" == "keygen" ]]; then
    TMPKEY=$(mktemp)
    ssh-keygen -t ed25519 -f "$TMPKEY" -N "" -C "proxmon@$(hostname)" -q
    SSH_PRIVATE_KEY=$(cat "$TMPKEY")
    PUBKEY=$(cat "${TMPKEY}.pub")
    rm -f "$TMPKEY" "${TMPKEY}.pub"

    mkdir -p "$SSH_DIR"
    echo "$PUBKEY" > "$SSH_DIR/authorized_keys"
    chown -R "$SSH_USER:$SSH_USER" "$SSH_DIR"
    chmod 700 "$SSH_DIR"
    chmod 600 "$SSH_DIR/authorized_keys"
    log_created "$SSH_DIR/authorized_keys (generated key pair)"
    info "Generated Ed25519 key pair and installed public key"
    SSH_AUTH_METHOD="key-based (generated)"

elif [[ "$MODE" == "password" ]]; then
    SSH_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)
    echo "$SSH_USER:$SSH_PASSWORD" | chpasswd
    log_created "Password for system user '$SSH_USER'"
    info "Set password for '$SSH_USER'"
    SSH_AUTH_METHOD="password"
fi

echo ""

# -----------------------------------------------------------------------
# SUMMARY
# -----------------------------------------------------------------------

echo "=============================="
echo "  Changes Made"
echo "=============================="
for entry in "${CHANGES[@]+"${CHANGES[@]}"}"; do
    echo "  $entry"
done
for entry in "${SKIPPED[@]+"${SKIPPED[@]}"}"; do
    echo "  $entry"
done

echo ""
echo "=============================="
echo "  Proxmon Settings"
echo "=============================="
echo ""
echo "  API Token ID:      $PVE_TOKEN_ID"
echo "  API Token Secret:  $TOKEN_SECRET"
echo ""
echo "  SSH Username:      $SSH_USER"
echo "  SSH Auth Method:   $SSH_AUTH_METHOD"
if [[ -n "$SSH_PASSWORD" ]]; then
    echo "  SSH Password:      $SSH_PASSWORD"
fi
if [[ -n "$SSH_PRIVATE_KEY" ]]; then
    echo ""
    echo "  SSH Private Key (paste this into Proxmon Settings → SSH):"
    echo "  ─────────────────────────────────────────────────────────"
    echo "$SSH_PRIVATE_KEY"
    echo "  ─────────────────────────────────────────────────────────"
fi
echo ""
echo "  Use these values in your Proxmon settings."
echo ""
