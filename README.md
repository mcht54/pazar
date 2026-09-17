# Mchttasarım Marketing OS

Mchttasarım Reklam Ajansı için AI destekli pazarlama operasyon platformu. Tasarım dokümanı: [docs/plans/2026-09-18-mchttasarim-marketing-os-design.md](docs/plans/2026-09-18-mchttasarim-marketing-os-design.md).

## Mimari

- **apps/api** — FastAPI backend
- **apps/web** — Next.js panel (bölge/sektör seçimi, discovery sonuçları, işletme detay/analiz ekranı)
- **services/worker** — Celery worker (discovery/analysis/proposal/reporting görevleri)
- **services/ai_orchestration** — deterministik evidence extraction + opsiyonel AI yorumlama katmanı
- **services/rule_engine** — deterministik hizmet eşleştirme, opportunity scoring, competitor comparison
- **services/integrations/** — her dış servis kendi klasöründe, `policy.py` ile kota/ToS/cache kuralları; `google_places` ve `website_crawler` altında hem gerçek (`google`/`Real...`) hem **mock/demo** provider'lar var
- **packages/db** — SQLAlchemy modelleri + Alembic migration'ları
- **tests/** — pytest paketi (Google API'siz, tamamen mock modda çalışır)

## Google API Anahtarı Gerekmez (Mock/Demo Mod)

Bu proje **hiçbir Google API anahtarı olmadan** local'de tamamen çalışır. `.env` dosyasında:

```bash
DISCOVERY_PROVIDER=mock   # varsayılan — Google Places yerine kurgusal DEMO işletme verisi üretir
AI_PROVIDER=none          # varsayılan — Claude API anahtarı yoksa AI yorumlama aşaması atlanır (skipped)
```

Mock moddayken üretilen tüm işletmeler `discovery_source=mock_demo` ve panelde
**"DEMO DATA — Gerçek Google verisi değildir"** etiketiyle işaretlenir. `AI_PROVIDER=none`
iken Finding/Rule Engine/Opportunity Score/Service Recommendation üretimi **etkilenmez** —
bunlar tamamen deterministik, AI'dan bağımsız çalışır. Sadece "AI yorumu" alanı boş kalır.

## Kurulum ve Çalıştırma — Docker Compose (önerilen)

```bash
cp .env.example .env
# .env dosyasını olduğu gibi bırakabilirsiniz (DISCOVERY_PROVIDER=mock, AI_PROVIDER=none) —
# gerçek bir Google/Anthropic anahtarı olmadan da sistem tam çalışır.

docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m packages.db.seed
```

- **Panel:** http://localhost:3000
- **Backend API:** http://localhost:8000 (health check: `/api/health`)

## Environment Variables (`.env`)

| Değişken | Açıklama | Zorunlu mu? |
|---|---|---|
| `DATABASE_URL` | Postgres bağlantısı | Evet |
| `REDIS_URL` | Celery broker/result backend | Evet |
| `DISCOVERY_PROVIDER` | `mock` (varsayılan, anahtar gerekmez) veya `google` | Hayır |
| `AI_PROVIDER` | `none` (varsayılan) veya `claude` | Hayır |
| `GOOGLE_PLACES_API_KEY` | Sadece `DISCOVERY_PROVIDER=google` iken | Sadece live modda |
| `GOOGLE_PAGESPEED_API_KEY` | Faz 2 web performans analizi için | Hayır (henüz kullanılmıyor) |
| `ANTHROPIC_API_KEY` | Sadece `AI_PROVIDER=claude` iken | Sadece AI yorumlama açıksa |
| `API_SECRET_KEY`, `API_CORS_ORIGINS` | Backend güvenlik/CORS ayarları | Evet (varsayılanlar yeterli, dev için) |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend'in API'ye erişeceği adres | Evet |

**Güvenlik:** `.env` asla Git'e eklenmez (`.gitignore`'da). Gerçek anahtarlar sadece `.env` içinde tutulur, `.env.example` her zaman secretsiz kalır.

## Database Migration ve Seed

```bash
alembic upgrade head          # şemayı oluşturur/günceller
python -m packages.db.seed    # bölge/sektör/hizmet kataloğu/integrations_registry seed verisi (idempotent)
```

Yeni migration oluşturmak için:
```bash
alembic revision --autogenerate -m "kısa açıklama"
alembic upgrade head
```

## Yerel Geliştirme (Docker olmadan)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Postgres ve Redis'in yerelde çalıştığından emin olun (ör. brew services start postgresql@16 redis), sonra:
export DATABASE_URL=postgresql+psycopg://<kullanıcı>@localhost:5432/mchttasarim_dev
export REDIS_URL=redis://localhost:6379/0
export DISCOVERY_PROVIDER=mock
export AI_PROVIDER=none

alembic upgrade head
python -m packages.db.seed

uvicorn apps.api.main:app --reload --port 8000          # terminal 1
celery -A services.worker.celery_app worker --loglevel=info -P solo   # terminal 2 (macOS'ta -P solo)

cd apps/web && npm install && npm run dev               # terminal 3 — http://localhost:3000
```

## Live Google Mode (ileride, gerçek API anahtarıyla)

1. Google Cloud Console'dan Places API (New) için bir anahtar oluşturun.
2. `.env` içinde `DISCOVERY_PROVIDER=google` ve `GOOGLE_PLACES_API_KEY=<anahtar>` girin.
3. `services/integrations/google_places/google_provider.py` içindeki Nearby/Text Search +
   Place Details implementasyonu tamamlanmalı (şu an kota/retry/timeout iskeleti hazır,
   gerçek çağrılar `NotImplementedError` fırlatıyor — bkz. dosya içi TODO).
4. `integrations_registry` tablosundaki `google_places` satırını (kota/cache/attribution)
   Google'ın güncel kurallarına göre gözden geçirin.

`DISCOVERY_PROVIDER=mock` iken `GooglePlacesProvider` hiçbir zaman import/instantiate edilmez.

## Testler

```bash
createdb mchttasarim_test   # bir kereye mahsus
pytest tests/ -v
```

Test paketi Google API'siz, tamamen `DISCOVERY_PROVIDER=mock` ile çalışır; Celery worker
gerektirmez (pipeline fonksiyonları doğrudan çağrılır — Celery sadece taşıma katmanıdır).

## Durum

Sprint 0 ve Sprint 1 tamamlandı — bkz. proje raporları. Sıradaki: Faz 2 (derin rakip/SEO/sosyal medya analizi, PDF teklif, gelişmiş CRM akışları).
