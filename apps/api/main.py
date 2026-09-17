from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.base import get_db
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Mchttasarım Marketing OS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.env}


@app.get("/api/health/db")
def health_db(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
