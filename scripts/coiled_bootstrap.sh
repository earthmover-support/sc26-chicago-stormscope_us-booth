#!/usr/bin/env bash
# Install the pipeline dependencies into the NGC PhysicsNeMo container on a Coiled GPU VM,
# then run the pipeline with the given arguments.
# See docs/GPU.md for the full `coiled run` command (--ami-version DL, no --keepalive).
#
# Each step prints a `[bootstrap]` marker, and a failure prints the line and exit code,
# so the Coiled logs show where a run stopped. The installs are skipped when they are
# already done (a rerun on the same kept-alive VM).
set -euo pipefail
trap 'echo "[bootstrap] FAILED at line $LINENO (exit $?): $BASH_COMMAND"' ERR
step() { echo "[bootstrap] $(date -u +%H:%M:%S) $*"; }

EARTH2STUDIO_VERSION=0.20.0
EARTH2GRID_COMMIT=11dcf1b0787a7eb6a8497a3a5a5e1fdcc31232d3
PY=$(command -v python)
step "python: $PY ($($PY --version 2>&1))"

step "nvidia-smi"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv

if ! $PY -c "import natten, earth2grid, earth2studio" 2>/dev/null; then
    step "pip: earth2studio + ingest deps"
    $PY -m pip list --format=freeze \
        | grep -iE '^(torch|torchvision|torchaudio|triton|nvidia-physicsnemo|numpy)==' \
        > /tmp/base-constraints.txt
    $PY -m pip install -q --root-user-action=ignore --no-cache-dir -c /tmp/base-constraints.txt \
        "earth2studio==${EARTH2STUDIO_VERSION}" "icechunk>=2.2" "arraylake>=1.3" \
        "pyproj>=3.7.1" "scipy>=1.15.2" "nvtx>=0.2.11" "omegaconf>=2.3.0" python-dotenv
    step "pip: natten"
    $PY -m pip install -q --root-user-action=ignore natten==0.21.7+torch2130cu132 -f https://whl.natten.org
    step "pip: earth2grid (source build)"
    $PY -m pip install -q --root-user-action=ignore --no-cache-dir --no-build-isolation \
        -c /tmp/base-constraints.txt \
        "earth2grid @ https://github.com/NVlabs/earth2grid/archive/${EARTH2GRID_COMMIT}.tar.gz"
fi

step "torch CUDA check"
$PY -c "import torch; print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.get_device_name(0))"

# Brev (scripts/brev_service.sh) installs once and commits the container to an image.
if [ -n "${BOOTSTRAP_INSTALL_ONLY:-}" ]; then
    step "install only: done"
    exit 0
fi

step "pipeline $*"
export PYTHONUNBUFFERED=1
$PY scripts/stormscope_us_pipeline.py "$@"
step "done"
