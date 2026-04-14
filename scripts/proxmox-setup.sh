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
PVE_PRIVS="VM.Audit,VM.PowerMgmt,VM.Snapshot,VM.Backup,Datastore.Audit,Sys.Audit,VM.GuestAgent.Audit"
PVE_USER="proxmon@pve"
PVE_TOKEN_NAME="monitoring"
PVE_TOKEN_ID="${PVE_USER}!${PVE_TOKEN_NAME}"
SSH_USER="proxmon"
SUDOERS_FILE="/etc/sudoers.d/proxmon"

TOKEN_SECRET=""
SSH_AUTH_METHOD=""
SSH_PASSWORD=""
SSH_PRIVATE_KEY=""

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

# -----------------------------------------------------------------------
# DRY-RUN PHASE — detect current state, build plan (no changes made)
# -----------------------------------------------------------------------

PLAN=()
SUDOERS_LINE="$SSH_USER ALL=(root) NOPASSWD: /usr/sbin/pct exec *"

# --- API checks ---

ROLE_EXISTS=false
if pveum role list --output-format json 2>/dev/null | grep -q "\"$PVE_ROLE\""; then
    ROLE_EXISTS=true
fi

USER_EXISTS=false
if pveum user list --output-format json 2>/dev/null | grep -q "\"$PVE_USER\""; then
    USER_EXISTS=true
fi

TOKEN_EXISTS=false
if pveum user token list "$PVE_USER" --output-format json 2>/dev/null | grep -q "\"$PVE_TOKEN_NAME\""; then
    TOKEN_EXISTS=true
fi

# --- SSH checks ---

SUDO_INSTALLED=false
if dpkg -l sudo 2>/dev/null | grep -q '^ii'; then
    SUDO_INSTALLED=true
fi

SYSUSER_EXISTS=false
if id "$SSH_USER" &>/dev/null; then
    SYSUSER_EXISTS=true
fi

SUDOERS_CONFIGURED=false
if [[ -f "$SUDOERS_FILE" ]] && grep -qF "$SUDOERS_LINE" "$SUDOERS_FILE"; then
    SUDOERS_CONFIGURED=true
fi

# --- Build plan ---

# API plan
if $ROLE_EXISTS; then
    PLAN+=("API|[SKIP]    PVE role '$PVE_ROLE' (already exists)")
else
    PLAN+=("API|[CREATE]  PVE role '$PVE_ROLE' with privs: $PVE_PRIVS")
fi

if $USER_EXISTS; then
    PLAN+=("API|[SKIP]    PVE user '$PVE_USER' (already exists)")
else
    PLAN+=("API|[CREATE]  PVE user '$PVE_USER'")
fi

if $TOKEN_EXISTS; then
    PLAN+=("API|[UPDATE]  API token '$PVE_TOKEN_ID' (remove + recreate to reveal secret)")
else
    PLAN+=("API|[CREATE]  API token '$PVE_TOKEN_ID'")
fi

PLAN+=("API|[UPDATE]  ACL: assign '$PVE_ROLE' to '$PVE_USER' on /")

# SSH plan
if $SUDO_INSTALLED; then
    PLAN+=("SSH|[SKIP]    sudo package (already installed)")
else
    PLAN+=("SSH|[INSTALL] sudo package (required for sudoers)")
fi

if $SYSUSER_EXISTS; then
    PLAN+=("SSH|[SKIP]    System user '$SSH_USER' (already exists)")
else
    PLAN+=("SSH|[CREATE]  System user '$SSH_USER'")
fi

if $SUDOERS_CONFIGURED; then
    PLAN+=("SSH|[SKIP]    $SUDOERS_FILE (already configured)")
else
    PLAN+=("SSH|[CREATE]  $SUDOERS_FILE")
fi

if [[ "$MODE" == "keygen" ]]; then
    PLAN+=("SSH|[CREATE]  Ed25519 SSH key pair for '$SSH_USER'")
else
    PLAN+=("SSH|[CREATE]  Random password for '$SSH_USER'")
fi

# -----------------------------------------------------------------------
# DISPLAY PLAN
# -----------------------------------------------------------------------

echo ""
echo "=== Proxmon Proxmox Setup ==="
echo ""
echo "The following actions will be performed:"
echo ""

echo "--- API Setup ---"
for entry in "${PLAN[@]}"; do
    section="${entry%%|*}"
    action="${entry#*|}"
    if [[ "$section" == "API" ]]; then
        echo "  $action"
    fi
done

echo ""
echo "--- SSH Setup ---"
for entry in "${PLAN[@]}"; do
    section="${entry%%|*}"
    action="${entry#*|}"
    if [[ "$section" == "SSH" ]]; then
        echo "  $action"
    fi
done

echo ""

# -----------------------------------------------------------------------
# PROMPT FOR CONFIRMATION
# -----------------------------------------------------------------------

read -rp "Proceed with the above changes? (y/N): " CONFIRM
if [[ "${CONFIRM,,}" != "y" ]]; then
    echo ""
    echo "Aborted. No changes were made."
    exit 0
fi

echo ""

# -----------------------------------------------------------------------
# EXECUTE — API SETUP
# -----------------------------------------------------------------------

echo "--- Applying API Setup ---"
echo ""

# 1. Role
if $ROLE_EXISTS; then
    info "Role '$PVE_ROLE' already exists"
else
    pveum role add "$PVE_ROLE" -privs "$PVE_PRIVS"
    info "Created role '$PVE_ROLE'"
fi

# 2. User
if $USER_EXISTS; then
    info "User '$PVE_USER' already exists"
else
    pveum user add "$PVE_USER"
    info "Created user '$PVE_USER'"
fi

# 3. API Token (always regenerate — Proxmox only reveals the secret at creation)
if $TOKEN_EXISTS; then
    pveum user token remove "$PVE_USER" "$PVE_TOKEN_NAME" >/dev/null 2>&1
    info "Removed existing token '$PVE_TOKEN_ID'"
fi
TOKEN_OUTPUT=$(pveum user token add "$PVE_USER" "$PVE_TOKEN_NAME" -privsep 0 --output-format json 2>&1)
TOKEN_SECRET=$(echo "$TOKEN_OUTPUT" | grep -oP '"value"\s*:\s*"\K[^"]+' || echo "$TOKEN_OUTPUT")
info "Created token '$PVE_TOKEN_ID'"

# 4. ACL
pveum acl modify / -user "$PVE_USER" -role "$PVE_ROLE"
info "Assigned role '$PVE_ROLE' to '$PVE_USER' on /"

echo ""

# -----------------------------------------------------------------------
# EXECUTE — SSH SETUP
# -----------------------------------------------------------------------

echo "--- Applying SSH Setup ---"
echo ""

# 1. Install sudo
if $SUDO_INSTALLED; then
    info "sudo already installed"
else
    apt-get update -qq && apt-get install -y -qq sudo
    info "Installed sudo"
fi

# 2. System user
if $SYSUSER_EXISTS; then
    info "System user '$SSH_USER' already exists"
else
    useradd -r -m -s /bin/bash "$SSH_USER"
    info "Created system user '$SSH_USER'"
fi

# 3. Sudoers
if $SUDOERS_CONFIGURED; then
    info "Sudoers already configured"
else
    echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    info "Created sudoers rule: $SUDOERS_LINE"
fi

# 4. SSH auth
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
    info "Generated Ed25519 key pair and installed public key"
    SSH_AUTH_METHOD="key-based (generated)"

elif [[ "$MODE" == "password" ]]; then
    SSH_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)
    echo "$SSH_USER:$SSH_PASSWORD" | chpasswd
    info "Set password for '$SSH_USER'"
    SSH_AUTH_METHOD="password"
fi

echo ""

# -----------------------------------------------------------------------
# CREDENTIALS SUMMARY
# -----------------------------------------------------------------------

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
