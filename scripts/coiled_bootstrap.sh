#!/usr/bin/env bash
# Install the pipeline dependencies into the NGC PhysicsNeMo container on a Coiled GPU VM,
# then run the pipeline with the given arguments. Mirrors the Dockerfile (keep in sync).
#
#   uv run coiled run --workspace earthmover-devs --region us-east-1 --ami-version DL --vm-type p5.4xlarge \
#     --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
#     --file scripts/ -- bash scripts/coiled_bootstrap.sh --n-steps 3 --start-time 2026-11-09T12:00
set -euo pipefail

EARTH2STUDIO_VERSION=0.20.0
EARTH2GRID_COMMIT=11dcf1b0787a7eb6a8497a3a5a5e1fdcc31232d3

nvidia-smi
pip list --format=freeze \
    | grep -iE '^(torch|torchvision|torchaudio|triton|nvidia-physicsnemo|numpy)==' \
    > /tmp/base-constraints.txt
pip install -q --no-cache-dir -c /tmp/base-constraints.txt \
    "earth2studio==${EARTH2STUDIO_VERSION}" "icechunk>=2.2" "arraylake>=1.3" \
    "pyproj>=3.7.1" "scipy>=1.15.2" "nvtx>=0.2.11" "omegaconf>=2.3.0" python-dotenv
pip install -q natten==0.21.7+torch2130cu132 -f https://whl.natten.org
pip install -q --no-cache-dir --no-build-isolation -c /tmp/base-constraints.txt \
    "earth2grid @ https://github.com/NVlabs/earth2grid/archive/${EARTH2GRID_COMMIT}.tar.gz"

export PYTHONUNBUFFERED=1
exec python scripts/stormscope_us_pipeline.py "$@"
