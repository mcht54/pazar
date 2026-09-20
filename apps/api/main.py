import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.routers import admin, analysis, auth, businesses, crm, dashboard, discovery, follow_ups, guides, regions, reports, sales, users
from packages.config import settings
from packages.db.base import get_db

logger = logging.getLogger("mchttasarim.api")

app = FastAPI(title="Mchttasarım Marketing OS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # oturum çerezi (HttpOnly) için; origin listesi açıkça belirtilmelidir
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Auth", "Content-Disposition"],
)

@app.on_event("startup")
def _normalize_legacy_crm_stages() -> None:
    """Eski durum adı yazan eski süreçlerin bıraktığı kayıtları yeni adlara çevirir (idempotent; hata API'yi açılmaktan alıkoymaz)."""
    from packages.db.base import SessionLocal
    from services import crm_service

    try:
        with SessionLocal() as db:
            fixed = crm_service.normalize_legacy_stages(db)
        if fixed:
            logger.info("CRM: %d eski durum adı yeni adlara çevrildi", fixed)
    except Exception:  # noqa: BLE001
        logger.exception("Eski CRM durum adları normalize edilemedi")


def env_misconfiguration_warnings() -> list[str]:
    """Üretim adresi (https) ile ENV=development çelişkisi: çerez Secure olmaz, /api/health yanıltıcı görünür. Secret değerleri asla yazılmaz."""
    warnings = []
    if settings.env == "development" and settings.web_base_url.lower().startswith("https://"):
        warnings.append("ENV=development ama WEB_BASE_URL https adresi (%s): sunucu .env dosyasında ENV=production olmalı." % settings.web_base_url)
    return warnings


@app.on_event("startup")
def _warn_env_misconfiguration() -> None:
    for message in env_misconfiguration_warnings():
        logger.warning(message)


CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "mch-app"


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """CSRF koruması (çerez tabanlı oturum için): değiştirici isteklerde özel başlık zorunludur. Başka bir site bu başlığı
    CORS onayı olmadan gönderemez; SameSite=Lax çerezi ile birlikte çapraz site istek sahteciliğini engeller."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        return JSONResponse(status_code=403, content={"detail": "Geçersiz istek kaynağı (CSRF koruması)."})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Sunucu tarafında beklenmeyen bir hata oluştu."})


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(regions.router)
app.include_router(discovery.router)
app.include_router(businesses.router)
app.include_router(analysis.router)
app.include_router(dashboard.router)
app.include_router(guides.router)
app.include_router(crm.router)
app.include_router(follow_ups.router)
app.include_router(reports.router)
app.include_router(sales.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
        "discovery_provider": settings.discovery_provider,
        "google_places_configured": bool(settings.google_places_api_key),
        "is_real_data_source": settings.discovery_provider in ("google_maps", "google"),
    }


@app.get("/api/health/db")
def health_db(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
