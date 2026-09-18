# Mchttasarım Marketing OS

Mchttasarım Reklam Ajansı için AI destekli pazarlama operasyon platformu. Tasarım dokümanı: [docs/plans/2026-09-18-mchttasarim-marketing-os-design.md](docs/plans/2026-09-18-mchttasarim-marketing-os-design.md).

## Mimari

- **apps/api** — FastAPI backend
- **apps/web** — Next.js panel (il/ilçe/sektör seçimi, discovery sonuçları, işletme detay/analiz ekranı)
- **services/worker** — Celery worker (discovery/analysis/proposal/reporting görevleri)
- **services/ai_orchestration** — deterministik evidence extraction + opsiyonel AI yorumlama katmanı
- **services/rule_engine** — deterministik hizmet eşleştirme, opportunity scoring, competitor comparison
- **services/integrations/** — her dış servis kendi klasöründe, `policy.py` ile kota/ToS/cache kuralları. `google_places` altında üç provider var: `overpass_provider.py` (OSM, gerçek veri, varsayılan), `google_provider.py` (Google Places API New, gerçek veri, anahtar gerekir), `mock_provider.py` (sadece test).
- **packages/db** — SQLAlchemy modelleri + Alembic migration'ları + Türkiye il/ilçe statik veri seti
- **tests/** — pytest paketi (gerçek ağ çağrısı yapmadan, mock'lanmış HTTP yanıtlarıyla çalışır)

## Gerçek Veri Kaynakları — Google API Anahtarı Şart Değil

Discovery iki gerçek veri kaynağını destekler; **hangisinin aktif olduğu panelde her zaman açıkça gösterilir** (yeşil rozet = gerçek veri, sarı rozet = demo/mock):

| `DISCOVERY_PROVIDER` | Kaynak | Anahtar gerekir mi? | Notlar |
|---|---|---|---|
| `osm` (**varsayılan**) | OpenStreetMap Overpass API | Hayır | Ücretsiz, gerçek işletme verisi. Rating/yorum sayısı OSM'de yok (`not_available`, asla uydurulmaz). Bazı bölge+sektör kombinasyonlarında kapsam zayıf olabilir — sonuç azsa arama alanı otomatik genişletilir. |
| `google` | Google Places API (New) — Text Search | Evet (`GOOGLE_PLACES_API_KEY`) | Daha hızlı, daha kapsamlı, rating/yorum/açılış saati dahil. Ücretli/faturalı Google Cloud hesabı gerektirir. |
| `mock` | Kurgusal veri üreteci | Hayır | **Sadece testler için.** Normal kullanımda seçilmemeli — seçilirse panelde büyük bir "DEMO/MOCK mod aktif" uyarısı çıkar. |

Google anahtarınız varsa tek yapmanız gereken `.env`'de `DISCOVERY_PROVIDER=google` ve `GOOGLE_PLACES_API_KEY=<anahtarınız>` yazmak — kod değişikliği gerekmez.

## Kurulum ve Çalıştırma — Docker Compose (önerilen)

```bash
cp .env.example .env
# Varsayılan haliyle bırakabilirsiniz (DISCOVERY_PROVIDER=osm) — hiçbir anahtar olmadan gerçek veri gelir.

docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m packages.db.seed
```

- **Panel:** http://localhost:3000
- **Backend API:** http://localhost:8000 (health check: `/api/health` — `discovery_provider` ve `google_places_configured` alanlarını gösterir)

## Environment Variables (`.env`)

| Değişken | Açıklama | Zorunlu mu? |
|---|---|---|
| `DATABASE_URL` | Postgres bağlantısı | Evet |
| `REDIS_URL` | Celery broker/result backend | Evet |
| `DISCOVERY_PROVIDER` | `osm` (varsayılan, gerçek veri, anahtar gerekmez) / `google` / `mock` (sadece test) | Hayır |
| `AI_PROVIDER` | `none` (varsayılan) veya `claude` | Hayır |
| `GOOGLE_PLACES_API_KEY` | Sadece `DISCOVERY_PROVIDER=google` iken | Sadece bu modda |
| `GOOGLE_PAGESPEED_API_KEY` | Faz 2 web performans analizi için | Hayır (henüz kullanılmıyor) |
| `ANTHROPIC_API_KEY` | Sadece `AI_PROVIDER=claude` iken | Sadece AI yorumlama açıksa |
| `API_SECRET_KEY`, `API_CORS_ORIGINS` | Backend güvenlik/CORS ayarları | Evet (varsayılanlar yeterli, dev için) |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend'in API'ye erişeceği adres | Evet |

**Güvenlik:** `.env` asla Git'e eklenmez (`.gitignore`'da). API anahtarları sadece backend'de (`.env` üzerinden) okunur, frontend koduna hiçbir zaman yazılmaz. `.env.example` her zaman secretsiz kalır.

## Database Migration ve Seed

```bash
alembic upgrade head          # şemayı oluşturur/günceller
python -m packages.db.seed    # 81 il + tüm ilçeler, 55+ sektör, hizmet kataloğu, integrations_registry (idempotent)
```

Türkiye il/ilçe verisi `packages/db/data/turkey_locations.json` dosyasında statik olarak tutulur —
uygulama çalışırken hiçbir zaman internetten aranmaz, seed sırasında tek seferde DB'ye yüklenir.

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
export DISCOVERY_PROVIDER=osm
export AI_PROVIDER=none

alembic upgrade head
python -m packages.db.seed

uvicorn apps.api.main:app --reload --port 8000          # terminal 1
celery -A services.worker.celery_app worker --loglevel=info -P solo   # terminal 2 (macOS'ta -P solo)

cd apps/web && npm install && npm run dev               # terminal 3 — http://localhost:3000
```

## Google Places Modu Nasıl Açılır

1. Google Cloud Console'da bir proje açıp Places API (New) için faturalandırma etkinleştirilmiş bir API anahtarı oluşturun.
2. `.env` içinde `DISCOVERY_PROVIDER=google` ve `GOOGLE_PLACES_API_KEY=<anahtarınız>` yazın.
3. Servisleri yeniden başlatın — kod değişikliği gerekmez, panel otomatik olarak "Google Places API" veri kaynağı rozetini gösterir.

`DISCOVERY_PROVIDER=osm`/`mock` iken `GooglePlacesProvider` hiçbir zaman import/instantiate edilmez; anahtar boşsa `google` seçilirse açık bir hata mesajıyla durur (sessizce mock'a düşmez).

## Testler

```bash
createdb mchttasarim_test   # bir kereye mahsus
pytest tests/ -v
```

Test paketi gerçek ağ çağrısı yapmaz — hem OSM hem Google provider'ları mock'lanmış HTTP
yanıtlarıyla test edilir; Celery worker de gerektirmez (pipeline fonksiyonları doğrudan
çağrılır, Celery sadece taşıma katmanıdır).

## Durum

Sprint 0-2 tamamlandı — bkz. proje raporları. Sıradaki: profesyonel dashboard arayüzü, derin rakip/SEO/sosyal medya analizi, PDF teklif, gelişmiş CRM akışları.
