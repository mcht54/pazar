# Mchttasarım Marketing OS

Mchttasarım Reklam Ajansı için AI destekli pazarlama operasyon platformu. Tasarım dokümanı: [docs/plans/2026-09-18-mchttasarim-marketing-os-design.md](docs/plans/2026-09-18-mchttasarim-marketing-os-design.md).

## Mimari

- **apps/api** — FastAPI backend
- **apps/web** — Next.js panel
- **services/worker** — Celery worker (discovery/analysis/proposal/reporting görevleri)
- **services/ai_orchestration** — Claude pipeline'ları
- **services/rule_engine** — deterministik hizmet eşleştirme
- **services/integrations/** — her dış servis kendi klasöründe, `policy.py` ile kota/ToS/cache kuralları
- **packages/db** — SQLAlchemy modelleri + Alembic migration'ları

## Docker Compose ile çalıştırma (önerilen)

```bash
cp .env.example .env   # gerçek API anahtarlarını buraya gir, .env asla commit edilmez
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m packages.db.seed
```

- Panel: http://localhost:3000
- API: http://localhost:8000/api/health

## Yerel geliştirme (Docker olmadan)

Bu repo Docker olmadan da (Postgres + Redis yerelde kurulu olacak şekilde) çalıştırılabilir — Sprint 0 bu şekilde test edildi.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Postgres ve Redis'in yerelde çalıştığından emin ol, sonra:
export DATABASE_URL=postgresql+psycopg://<kullanıcı>@localhost:5432/mchttasarim_dev
export REDIS_URL=redis://localhost:6379/0

alembic upgrade head
python -m packages.db.seed

uvicorn apps.api.main:app --reload --port 8000
celery -A services.worker.celery_app worker --loglevel=info   # ayrı terminalde

cd apps/web && npm install && npm run dev   # ayrı terminalde
```

## Yeni migration oluşturma

```bash
alembic revision --autogenerate -m "kısa açıklama"
alembic upgrade head
```

## Durum

Sprint 0 tamamlandı — bkz. proje raporu. Sıradaki: Sprint 1 (Region/Sector taxonomy + Discovery pipeline).
