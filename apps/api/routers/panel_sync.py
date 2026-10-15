"""MCHT Panel giriş senkronu ucu (bkz. services/auth/login_sync.py). Oturum çerezi KULLANMAZ; güvenlik HMAC imzası + zaman + nonce ile sağlanır."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from apps.api.deps import client_ip
from packages.db.base import get_db
from services.auth import login_sync

router = APIRouter(prefix="/api/mcht", tags=["panel senkronu"], include_in_schema=False)


@router.post("/giris-senkron")
async def giris_senkron(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        data = login_sync.verify(raw, request.headers.get("x-mcht-zaman", ""), request.headers.get("x-mcht-imza", ""))
        if data.get("islem") == "ping":
            return {"ok": True, "site": "Pazar (Satış Operasyon)", "surum": 1}
        if data.get("islem") != "kaydet":
            raise login_sync.SyncError(400, "Bilinmeyen işlem.")
        return login_sync.apply(db, data, ip=client_ip(request))
    except login_sync.SyncError as exc:
        return JSONResponse(status_code=exc.status, content={"ok": False, "hata": exc.message})
