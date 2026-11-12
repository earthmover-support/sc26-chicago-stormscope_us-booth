"""Load `scripts/stormscope_us_pipeline.py` as a module (scripts/ is not a package)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "stormscope_us_pipeline.py"


@pytest.fixture(scope="session")
def pipeline():
    spec = importlib.util.spec_from_file_location("stormscope_us_pipeline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
