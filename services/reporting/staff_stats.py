"""Personel bazlı raporlar (yönetici): analiz, arama, CRM işlemleri — hepsi kullanıcıyla ilişkili gerçek kayıtlardan.

- Analiz: analysis_jobs (trigger='user', tamamlanan/kısmi; başarısız sayılmaz)
- CRM: crm_activities (kullanıcı, durum değişimi 'Arandı'/'Teklif Gönderildi'/'Kazanıldı' ve iletişim kayıtları, ekleme, not)
- Arama/Dışa aktarma/Giriş: activity_log
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.db.models import ActivityLog, AnalysisJob, CrmActivity, User
from services.reporting.analysis_stats import COUNTED_STATUSES, PERIODS, period_bounds


def staff_report(db: Session, period: str = "today", now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    start, end = period_bounds(now)[period]

    def since(column):
        return ([column >= start] if start is not None else []) + ([column < end] if end is not None else [])

    analyses = dict(
        db.query(AnalysisJob.user_id, func.count(AnalysisJob.id))
        .filter(AnalysisJob.status.in_(COUNTED_STATUSES), AnalysisJob.trigger == "user", AnalysisJob.user_id.isnot(None), *since(AnalysisJob.completed_at))
        .group_by(AnalysisJob.user_id).all()
    )
    crm: dict[int, dict[str, int]] = {}
    for user_id, type_, to_stage, n in (
        db.query(CrmActivity.user_id, CrmActivity.type, CrmActivity.to_stage, func.count(CrmActivity.id))
        .filter(CrmActivity.user_id.isnot(None), *since(CrmActivity.created_at))
        .group_by(CrmActivity.user_id, CrmActivity.type, CrmActivity.to_stage).all()
    ):
        row = crm.setdefault(user_id, {"added": 0, "calls": 0, "offers": 0, "customers": 0, "notes": 0, "status_changes": 0})
        if type_ == "added":
            row["added"] += n
        if type_ == "note":
            row["notes"] += n
        if type_ == "contact":
            row["calls"] += n
        if type_ in ("status_change", "added"):
            row["status_changes"] += n if type_ == "status_change" else 0
            row["calls"] += n if to_stage == "Arandı" else 0
            row["offers"] += n if to_stage == "Teklif Gönderildi" else 0
            row["customers"] += n if to_stage == "Kazanıldı" else 0
    logs: dict[int, dict[str, int]] = {}
    for user_id, action, n in (
        db.query(ActivityLog.user_id, ActivityLog.action, func.count(ActivityLog.id))
        .filter(ActivityLog.user_id.isnot(None), ActivityLog.action.in_(("search", "export", "login")), *since(ActivityLog.created_at))
        .group_by(ActivityLog.user_id, ActivityLog.action).all()
    ):
        logs.setdefault(user_id, {})[action] = n

    rows = []
    for user in db.query(User).order_by(User.name).all():
        c, l = crm.get(user.id, {}), logs.get(user.id, {})
        row = {
            "user_id": user.id, "name": user.name, "role": user.role, "is_active": user.is_active,
            "analyses": analyses.get(user.id, 0), "searches": l.get("search", 0), "crm_added": c.get("added", 0), "calls": c.get("calls", 0),
            "offers": c.get("offers", 0), "customers": c.get("customers", 0), "notes": c.get("notes", 0), "status_changes": c.get("status_changes", 0),
            "exports": l.get("export", 0), "logins": l.get("login", 0),
        }
        if any(row[k] for k in ("analyses", "searches", "crm_added", "calls", "offers", "customers", "notes", "status_changes", "exports", "logins")) or user.is_active:
            rows.append(row)
    return {"period": period, "label": PERIODS[period], "since": start.isoformat() if start else None, "items": rows}
