#!/usr/bin/env bash
# Run by the systemd service `stormscope-us` that scripts/brev_setup.sh installs on a
# Brev VM. Runs the pipeline continuously in the NGC PhysicsNeMo container, as on Coiled
# (docs/GPU.md).
#
# The first start installs the dependencies with scripts/coiled_bootstrap.sh in a GPU
# container and commits it as the local image stormscope-us:<base tag>, so later restarts
# skip the installs. Delete that image to reinstall. The pipeline settings (publish target,
# Arraylake repo, token) come from /etc/stormscope-us/env.
set -euo pipefail
step() { echo "[brev-service] $(date -u +%H:%M:%S) $*"; }

APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_TAG=26.08
BASE_IMAGE=nvcr.io/nvidia/physicsnemo/physicsnemo:$BASE_TAG
IMAGE=stormscope-us:$BASE_TAG
NAME=stormscope-us
ENV_FILE=/etc/stormscope-us/env
STATE=/var/lib/stormscope-us  # model weights, pyspectral tables, torch.compile cache, local outputs
mkdir -p "$STATE/cache" "$STATE/outputs"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    step "install dependencies into $IMAGE (first start only)"
    docker rm -f "$NAME-build" >/dev/null 2>&1 || true
    docker run --name "$NAME-build" --gpus all -e BOOTSTRAP_INSTALL_ONLY=1 \
        -v "$APP_DIR/scripts:/work/scripts:ro" -w /work \
        "$BASE_IMAGE" bash scripts/coiled_bootstrap.sh
    docker commit "$NAME-build" "$IMAGE" >/dev/null
    docker rm "$NAME-build" >/dev/null
fi

step "pipeline (continuous, --n-steps 12)"
exec docker run --rm --name "$NAME" --gpus all --shm-size 1g \
    --env-file "$ENV_FILE" \
    -e TORCHINDUCTOR_CACHE_DIR=/root/.cache/torchinductor \
    -v "$STATE/cache:/root/.cache" \
    -v "$STATE/outputs:/work/outputs" \
    -v "$APP_DIR/scripts:/work/scripts:ro" -w /work \
    "$IMAGE" bash scripts/coiled_bootstrap.sh --n-steps 12
