import os
import subprocess
from pathlib import Path

os.environ["DATABASE_URL"] = f"postgresql+psycopg://{os.getenv('USER', 'postgres')}@localhost:5432/mchttasarim_test"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DISCOVERY_PROVIDER"] = "mock"
os.environ["AI_PROVIDER"] = "none"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    subprocess.run(["alembic", "upgrade", "head"], check=True, cwd=REPO_ROOT, env=os.environ.copy())
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    from packages.db.base import SessionLocal
    from packages.db.models import Base

    session = SessionLocal()
    table_names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    session.commit()
    session.close()


@pytest.fixture
def db():
    from packages.db.base import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_db(db):
    from packages.db import seed as seed_module

    seed_module.run()
    return db


@pytest.fixture
def client(seeded_db):
    from apps.api.main import app

    return TestClient(app)
