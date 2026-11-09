# syntax=docker/dockerfile:1
# StormScope-US pipeline (scripts/stormscope_us_pipeline.py) on a CUDA GPU host.
# Start it with `docker compose up -d` (see compose.yaml), which also supplies the credentials.

FROM nvcr.io/nvidia/physicsnemo/physicsnemo:26.08

ARG EARTH2STUDIO_VERSION=0.20.0
ARG EARTH2GRID_COMMIT=11dcf1b0787a7eb6a8497a3a5a5e1fdcc31232d3

# The base image's torch, physicsnemo and numpy are CUDA builds; pin them so pip resolves
# the packages below around them instead of swapping in PyPI wheels.
RUN pip list --format=freeze \
    | grep -iE '^(torch|torchvision|torchaudio|triton|nvidia-physicsnemo|numpy)==' \
    > /opt/base-constraints.txt

# earth2studio without extras: [data] pulls cfgrib/eccodes, which the GOES source does not
# need. What StormScopeGOES and the Icechunk ingest use from the extras is listed here.
RUN pip install --no-cache-dir -c /opt/base-constraints.txt \
    "earth2studio==${EARTH2STUDIO_VERSION}" \
    "icechunk>=2.2" \
    "arraylake>=1.3" \
    "pyproj>=3.7.1" \
    "scipy>=1.15.2" \
    "nvtx>=0.2.11" \
    "omegaconf>=2.3.0"

# NATTEN (neighborhood attention) and earth2grid (GOES -> HRRR nearest-neighbour regrid)
# are both required by StormScopeGOES; earth2grid builds against the image's torch.
RUN pip install natten==0.21.7+torch2130cu132 -f https://whl.natten.org
RUN pip install --no-cache-dir --no-build-isolation -c /opt/base-constraints.txt \
    "earth2grid @ https://github.com/NVlabs/earth2grid/archive/${EARTH2GRID_COMMIT}.tar.gz"

# Fail the build, not the first run, if a dependency is missing. physicsnemo modules are
# located rather than imported: importing them loads transformer_engine, which needs
# libcuda.so.1, and builds run without the GPU driver.
RUN python -c "\
import importlib.util, pathlib; \
import arraylake, earth2grid, earth2studio, icechunk, natten, nvtx, obstore, omegaconf, pyproj; \
from earth2studio.data import GOES; \
root = pathlib.Path(importlib.util.find_spec('physicsnemo').submodule_search_locations[0]); \
needed = ['models/dit', 'nn/module/dit_layers', 'nn/module/rope', 'utils/zenith_angle']; \
missing = [m for m in needed if not (root / m).is_dir() and not (root / m).with_suffix('.py').is_file()]; \
assert not missing, f'physicsnemo is missing {missing}'"

# Model checkpoint and downloaded GOES files; compose.yaml mounts a volume here.
ENV EARTH2STUDIO_CACHE=/cache/earth2studio \
    HF_HOME=/cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY scripts/ scripts/
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/stormscope-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/stormscope-entrypoint.sh"]
CMD ["python", "scripts/stormscope_us_pipeline.py"]
