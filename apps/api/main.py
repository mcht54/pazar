import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.routers import analysis, businesses, discovery, regions
from packages.config import settings
from packages.db.base import get_db

logger = logging.getLogger("mchttasarim.api")

app = FastAPI(title="Mchttasarım Marketing OS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Sunucu tarafında beklenmeyen bir hata oluştu."})


app.include_router(regions.router)
app.include_router(discovery.router)
app.include_router(businesses.router)
app.include_router(analysis.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.env, "discovery_provider": settings.discovery_provider}


@app.get("/api/health/db")
def health_db(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
