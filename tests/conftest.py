import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolated_sr_memory_db(tmp_path, monkeypatch):
    """The S/R memory system (app/data_sources/sr_memory_store.py)
    persists to a SQLite file by default -- tests must not read or write
    the real production database, and must not leak touch-count state
    between test functions either. Each test gets its own fresh,
    throwaway file."""
    monkeypatch.setattr(settings, "sr_memory_db_path", str(tmp_path / "test_sr_memory.db"))
