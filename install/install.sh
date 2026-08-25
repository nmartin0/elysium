#!/bin/sh
# install.sh  (Elysium: fresh install -- system user/group, FHS layout,
# systemd service, root bootstrap)
#
# Written in POSIX sh syntax throughout -- no bash-only features
# (arrays, [[ ]], process substitution). This does NOT make the script
# as a WHOLE portable to non-Linux POSIX systems: several of the
# COMMANDS it calls are Linux-specific, marked explicitly below. Using
# POSIX syntax for everything else means that if someone later swaps
# those Linux-specific commands for another platform's equivalents,
# they aren't also fighting a different shell dialect throughout.
#
# NOT idempotent for an existing install -- this is a FRESH-install
# script. Re-running it against an already-installed Elysium will not
# corrupt existing data (it will not re-bootstrap if credentials.db
# already exists, see below), but it is not an upgrade mechanism.
#
# Must be run as root: creates a system user, writes to /opt, /etc,
# /var/lib, /var/log, installs a systemd unit.

set -e

ELYSIUM_USER="elysium"
ELYSIUM_GROUP="elysium"
OPT_DIR="/opt/elysium"
ETC_DIR="/etc/elysium"
VAR_LIB_DIR="/var/lib/elysium"
VAR_LOG_DIR="/var/log/elysium"

# --- 0. Preconditions --------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run as root." >&2
    exit 1
fi

# Resolves the script's own directory, then one level up -- assumes
# this is being run from within a checked-out copy of the repository.
SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ ! -f "$SOURCE_DIR/requirements.txt" ]; then
    echo "Could not find requirements.txt in $SOURCE_DIR -- run this script from a checked-out copy of the repository." >&2
    exit 1
fi

# --- 1. System user + group ---------------------------------------------
#
# *** LINUX-SPECIFIC: useradd/groupadd/getent ***
# These come from shadow-utils and glibc -- near-universal on Linux,
# but NOT POSIX-specified utilities. BSD systems use `pw useradd`;
# macOS uses `dscl`. This whole section needs rewriting, not adapting,
# on a non-Linux POSIX system.

if ! getent group "$ELYSIUM_GROUP" >/dev/null 2>&1; then
    groupadd --system "$ELYSIUM_GROUP"
    echo "Created group: $ELYSIUM_GROUP"
fi

if ! getent passwd "$ELYSIUM_USER" >/dev/null 2>&1; then
    useradd --system --gid "$ELYSIUM_GROUP" --home-dir "$OPT_DIR" \
        --shell /usr/sbin/nologin --comment "Elysium service account" "$ELYSIUM_USER"
    echo "Created system user: $ELYSIUM_USER (no login shell)"
fi

# *** LINUX-SPECIFIC: $SUDO_USER is a sudo mechanism, not POSIX ***
# Absent under su/doas -- this step is silently skipped in that case
# rather than guessed at. Adds the actual human running this install
# to the group, so they can inspect logs/config without being the
# elysium service account itself.
if [ -n "$SUDO_USER" ]; then
    usermod --append --groups "$ELYSIUM_GROUP" "$SUDO_USER"
    echo "Added $SUDO_USER to group $ELYSIUM_GROUP"
fi

# --- 2. Directory layout -------------------------------------------------
#
# This specific FHS-based layout (/opt, /etc, /var/lib, /var/log used
# this way) is a Linux Foundation convention, NOT a POSIX-mandated
# directory hierarchy -- POSIX does not specify a full filesystem
# layout at all.
#
# /run/elysium is deliberately NOT created here -- see
# install/elysium.service's RuntimeDirectory= directive, systemd's own
# idiomatic mechanism for managing it.

mkdir -p "$OPT_DIR" "$ETC_DIR" "$VAR_LIB_DIR" "$VAR_LOG_DIR"

# --- 3. Application code -------------------------------------------------

cp -r "$SOURCE_DIR/core" "$SOURCE_DIR/adapters" "$SOURCE_DIR/tools" \
      "$SOURCE_DIR/api" "$SOURCE_DIR/scripts" "$SOURCE_DIR/requirements.txt" "$OPT_DIR/"

# --- 4. Python virtual environment ---------------------------------------

python3 -m venv "$OPT_DIR/venv"
"$OPT_DIR/venv/bin/pip" install --upgrade pip
"$OPT_DIR/venv/bin/pip" install -r "$OPT_DIR/requirements.txt"

# --- 5. Config + data, mirroring the source repository's own layout ------
#
# deployment/etc in the source checkout is laid out to EXACTLY mirror
# /etc/elysium -- a direct structural copy, not cherry-picked files,
# because local development and a real install share the SAME
# three-location model (see core/deployment_loader.py's
# resolve_runtime_paths() docstring).
#
# deployment/var/lib is NOT copied wholesale, deliberately: if the
# person running this install has ever run this software locally
# (e.g. to test), deployment/var/lib/credentials.db may already exist
# in the source checkout -- copying it would hand every fresh install
# the DEVELOPER'S OWN credentials, including their root password. Only
# dev_fixtures/ (the starting business data) is copied by name;
# credentials.db is always created fresh by the bootstrap step below.

cp -r "$SOURCE_DIR/deployment/etc/." "$ETC_DIR/"

if [ -d "$SOURCE_DIR/deployment/var/lib/dev_fixtures" ]; then
    cp -r "$SOURCE_DIR/deployment/var/lib/dev_fixtures" "$VAR_LIB_DIR/"
fi

# --- 6. Ownership + permissions ------------------------------------------
#
# Root ownership ends HERE -- everything below belongs to the elysium
# user/group for the running system's whole lifetime, never root.

chown -R "$ELYSIUM_USER:$ELYSIUM_GROUP" "$OPT_DIR" "$ETC_DIR" "$VAR_LIB_DIR" "$VAR_LOG_DIR"

chmod 750 "$OPT_DIR" "$ETC_DIR" "$VAR_LOG_DIR"
chmod 700 "$VAR_LIB_DIR"   # credentials.db lives here -- no group access at all

# --- 7. systemd service ----------------------------------------------------
#
# *** LINUX-SPECIFIC: systemd is not part of POSIX and has no portable
# equivalent -- a non-Linux system needs an entirely different service
# supervision mechanism here, not a translated unit file. ***

cp "$SOURCE_DIR/install/elysium.service" /etc/systemd/system/elysium.service
systemctl daemon-reload
systemctl enable elysium.service
echo "Installed and enabled the elysium systemd service (not started yet)."

# --- 8. Bootstrap the first admin user ------------------------------------
#
# Skipped if a credentials database already exists -- this script is
# for a FRESH install; re-running it must never silently create a
# second admin account or otherwise touch existing user data.

if [ -f "$VAR_LIB_DIR/credentials.db" ]; then
    echo ""
    echo "credentials.db already exists -- skipping root bootstrap (this looks like an existing install)."
else
    echo ""
    echo "Creating the first admin user..."
    # Environment variables are set INSIDE the su'd command itself,
    # not relied upon to survive through `su` -- su does not reliably
    # propagate the calling shell's environment.
    su -s /bin/sh "$ELYSIUM_USER" -c \
        "cd '$OPT_DIR' && ELYSIUM_CONFIG_DIR='$ETC_DIR' ELYSIUM_DATA_DIR='$VAR_LIB_DIR' ./venv/bin/python3 -m scripts.bootstrap_root root admin"
fi

echo ""
echo "Install complete. Start the service with: systemctl start elysium.service"
