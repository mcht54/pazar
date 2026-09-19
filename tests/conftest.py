import os
import subprocess
from pathlib import Path

os.environ["DATABASE_URL"] = f"postgresql+psycopg://{os.getenv('USER', 'postgres')}@localhost:5432/mchttasarim_test"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["DISCOVERY_PROVIDER"] = "mock"
os.environ["AI_PROVIDER"] = "none"
os.environ["RESEARCH_ENABLED"] = "false"  # testler Google/Bing/web sitesi gibi dış kaynaklara ASLA istek atmaz

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


CSRF_HEADERS = {"X-Requested-With": "mch-app"}
TEST_PASSWORD = "Deneme12345"


def make_user(db, role: str, *, name: str | None = None, email: str | None = None, username: str | None = None,
              password: str = TEST_PASSWORD, is_active: bool = True, must_change_password: bool = False):
    """Test kullanıcısı oluşturur (gerçek şifre özetiyle; düz metin saklanmaz)."""
    from packages.db.models import User
    from services.auth.security import hash_password

    key = f"{role}{db.query(User).count() + 1}"
    user = User(name=name or f"Test {role.title()}", email=email or f"{key}@example.test", username=username or key, role=role,
                password_hash=hash_password(password), is_active=is_active, must_change_password=must_change_password)
    db.add(user)
    db.commit()
    return user


def logged_in_client(user, password: str = TEST_PASSWORD):
    from apps.api.main import app

    test_client = TestClient(app, headers=CSRF_HEADERS)
    response = test_client.post("/api/auth/login", json={"identifier": user.email, "password": password})
    assert response.status_code == 200, response.text
    return test_client


@pytest.fixture
def anon_client(seeded_db):
    """Giriş yapmamış istemci (CSRF başlığı var)."""
    from apps.api.main import app

    return TestClient(app, headers=CSRF_HEADERS)


@pytest.fixture
def admin_user(seeded_db):
    return make_user(seeded_db, "yonetici", name="Test Yönetici", email="yonetici@example.test", username="yonetici")


@pytest.fixture
def client(seeded_db, admin_user):
    """VARSAYILAN test istemcisi: oturum açmış YÖNETİCİ (mevcut testler tüm yetkilerle çalışır). Rol/yetki testleri `login_as` kullanır."""
    return logged_in_client(admin_user)


@pytest.fixture
def login_as(seeded_db):
    """Fabrika: login_as("calisan") → o rolde oturum açmış istemci."""
    def factory(role: str, **kwargs):
        user = make_user(seeded_db, role, **kwargs)
        test_client = logged_in_client(user, kwargs.get("password", TEST_PASSWORD))
        test_client.user = user
        return test_client
    return factory
