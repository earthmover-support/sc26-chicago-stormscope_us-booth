#!/bin/bash
# Setup script for the StormScope-US Brev launchable (VM Mode). Paste it into the
# launchable's "Setup script" field; see docs/BREV.md.
#
# Brev passes the launchable's setup values as environment variables to this script only,
# and deletes them after setup. The script therefore:
#   1. clones this repo to /opt/stormscope-us at STORMSCOPE_GIT_REF,
#   2. stores the setup values in /etc/stormscope-us/env (root, mode 600),
#   3. installs and starts the systemd service `stormscope-us`, which runs
#      scripts/brev_service.sh and restarts it after a crash or a reboot.
#
# Setup values:
#   ARRAYLAKE_API_TOKEN        write token; required unless STORMSCOPE_PUBLISH_TARGET=local
#   ARRAYLAKE_REPO             default nvidia/sc26-chicago-stormscope_us-booth
#   STORMSCOPE_PUBLISH_TARGET  arraylake (default) or local
#   STORMSCOPE_GIT_REF         branch, tag or commit of this repo; default main
#
# Rerunning the script (with new values) updates the checkout and the env file and
# restarts the service. Do not add `set -x`: it would print the token to the setup log.
set -euo pipefail
step() { echo "[brev-setup] $(date -u +%H:%M:%S) $*"; }

GIT_URL=https://github.com/earthmover-support/sc26-chicago-stormscope_us-booth.git
GIT_REF=${STORMSCOPE_GIT_REF:-main}
APP_DIR=/opt/stormscope-us
ENV_FILE=/etc/stormscope-us/env
UNIT=stormscope-us
PUBLISH_TARGET=${STORMSCOPE_PUBLISH_TARGET:-arraylake}
REPO=${ARRAYLAKE_REPO:-nvidia/sc26-chicago-stormscope_us-booth}

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

case "$PUBLISH_TARGET" in
    arraylake)
        if [ -z "${ARRAYLAKE_API_TOKEN:-}" ]; then
            echo "[brev-setup] ARRAYLAKE_API_TOKEN is empty; set it in the launchable's setup values" >&2
            exit 1
        fi ;;
    local) ;;
    *) echo "[brev-setup] STORMSCOPE_PUBLISH_TARGET must be arraylake or local" >&2; exit 1 ;;
esac
for v in "${ARRAYLAKE_API_TOKEN:-}" "$REPO"; do
    case "$v" in *$'\n'*|*$'\r'*) echo "[brev-setup] setup values must be one line" >&2; exit 1 ;; esac
done

step "host GPU"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
command -v docker >/dev/null || { echo "[brev-setup] docker not found; use VM Mode" >&2; exit 1; }
$SUDO docker info --format '{{json .Runtimes}}' | grep -q nvidia \
    || echo "[brev-setup] WARNING: docker lists no nvidia runtime; --gpus may fail"

step "checkout $GIT_REF -> $APP_DIR"
$SUDO mkdir -p "$APP_DIR"
[ -d "$APP_DIR/.git" ] || $SUDO git -C "$APP_DIR" init -q
$SUDO git -C "$APP_DIR" fetch -q --depth 1 "$GIT_URL" "$GIT_REF"
$SUDO git -C "$APP_DIR" checkout -q --force FETCH_HEAD
$SUDO git -C "$APP_DIR" log -1 --format='[brev-setup] commit %h %s'

step "env file $ENV_FILE"
tmp=$(umask 077; mktemp)
{
    [ -n "${ARRAYLAKE_API_TOKEN:-}" ] && printf 'ARRAYLAKE_API_TOKEN=%s\n' "$ARRAYLAKE_API_TOKEN"
    printf 'ARRAYLAKE_REPO=%s\n' "$REPO"
    printf 'STORMSCOPE_PUBLISH_TARGET=%s\n' "$PUBLISH_TARGET"
} > "$tmp"
$SUDO install -D -m 600 -o root -g root "$tmp" "$ENV_FILE"
rm -f "$tmp"

step "systemd unit $UNIT"
$SUDO tee /etc/systemd/system/$UNIT.service >/dev/null <<EOF
[Unit]
Description=StormScope-US nowcast pipeline (GOES-19 -> Arraylake)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
ExecStartPre=-/bin/sh -c 'docker rm -f $UNIT >/dev/null 2>&1'
ExecStart=/bin/bash $APP_DIR/scripts/brev_service.sh
# systemd also runs ExecStop after the main process exits on its own, when the --rm
# container is already gone; '-' keeps that from masking the real exit status.
ExecStop=-/bin/sh -c 'docker stop -t 30 $UNIT >/dev/null 2>&1'
Restart=always
RestartSec=30
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
$SUDO systemctl daemon-reload
$SUDO systemctl enable -q $UNIT
$SUDO systemctl restart $UNIT

step "started; the first start pulls the container and installs the dependencies (~10-15 min)"
echo "[brev-setup] logs: sudo journalctl -u $UNIT -f"
