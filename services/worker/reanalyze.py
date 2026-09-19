"""Bakım aracı: mevcut işletmeleri yeniden analiz eder (yeni kurallar/puanlama/fırsat kartları yayına alındıktan sonra).

Kullanım:
    python -m services.worker.reanalyze --all               # analiz edilmiş tüm işletmeler (Google'a YENİ sorgu atmaz; önbellekteki araştırma kullanılır)
    python -m services.worker.reanalyze --ids 12,15,20      # yalnızca belirtilen işletmeler
    python -m services.worker.reanalyze --all --new-research  # önbelleği olmayanlar için Google/Bing araştırmasını da çalıştır (yavaş)
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from packages.db.base import SessionLocal
from packages.db.models import AnalysisJob, Business
from services.worker.tasks.analysis import run_analysis_job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="analiz edilmiş tüm işletmeler")
    parser.add_argument("--ids", help="virgülle ayrılmış işletme kimlikleri")
    parser.add_argument("--new-research", action="store_true", help="önbelleği olmayanlar için yeni Google/Bing araştırması yap")
    parser.add_argument("--workers", type=int, default=1, help="paralel iş parçacığı sayısı (web sitesi taramaları paralel yapılır)")
    args = parser.parse_args()
    if not args.all and not args.ids:
        parser.error("--all veya --ids gerekli")

    db = SessionLocal()
    try:
        query = db.query(Business).filter(Business.status.in_(("analyzed", "analysis_failed")))
        if args.ids:
            query = db.query(Business).filter(Business.id.in_([int(x) for x in args.ids.split(",")]))
        businesses = query.order_by(Business.id).all()
        ids = [b.id for b in businesses]
        print(f"{len(ids)} işletme yeniden analiz edilecek ({args.workers} paralel)…", flush=True)

        def work(business_id: int) -> tuple[int, str | None]:
            session = SessionLocal()
            try:
                job = AnalysisJob(business_id=business_id, trigger="maintenance")  # bakım: personel analiz sayaçlarına dahil edilmez
                session.add(job)
                business = session.get(Business, business_id)
                business.status = "analyzing"
                session.commit()
                try:
                    run_analysis_job(session, job.id, allow_new_research=args.new_research)
                    return business_id, None
                except Exception as exc:  # tek işletme hatası tüm işi durdurmasın
                    session.rollback()
                    return business_id, f"{type(exc).__name__}: {exc}"
            finally:
                session.close()

        ok = failed = 0
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for i, (business_id, error) in enumerate(pool.map(work, ids), 1):
                if error:
                    failed += 1
                    print(f"  [{business_id}] HATA {error}", flush=True)
                else:
                    ok += 1
                if i % 10 == 0:
                    print(f"  {i}/{len(ids)} …", flush=True)
        print(f"Bitti: {ok} başarılı, {failed} hatalı ({datetime.now(timezone.utc):%H:%M})", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
