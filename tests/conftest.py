import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from sems_ai.config.settings import Settings  # noqa: E402
from sems_ai.core.context import AppContext  # noqa: E402
from sems_ai.security import network_guard  # noqa: E402

import synthetic_docs  # noqa: E402


@pytest.fixture()
def settings(tmp_path) -> Settings:
    s = Settings.load(tmp_path / "data")
    s.llm_enabled = False
    s.block_outbound_network = True
    return s


@pytest.fixture()
def ctx(settings):
    c = AppContext(settings, username="tester")
    yield c
    network_guard.disable()


@pytest.fixture()
def docs(tmp_path) -> dict:
    return synthetic_docs.build_all(tmp_path / "input")


@pytest.fixture()
def loaded(ctx, docs):
    repo = ctx.repository
    out = {}
    out["std"] = repo.import_file(docs["standard_pdf"], "Estándares corporativos")
    out["plan"] = repo.import_file(docs["plan_docx"], "Planes de gestión")
    out["xlsx"] = repo.import_file(docs["xlsx"], "Evidencias")
    return out
