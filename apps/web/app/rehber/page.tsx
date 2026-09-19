"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { GuideSummary, Sector } from "@/lib/types";
import { GuideModal } from "../_components/sales";
import { trSort } from "../_components/labels";

export default function GuideLibraryPage() {
  const [categories, setCategories] = useState<string[]>([]);
  const [guides, setGuides] = useState<GuideSummary[]>([]);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [category, setCategory] = useState<string>("Hepsi");
  const [query, setQuery] = useState("");
  const [sectorId, setSectorId] = useState<number | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listGuides().then((r) => { setCategories(r.categories); setGuides(r.guides); }).catch((e) => setError(e.message));
    api.getSectors().then(setSectors).catch(() => {});
  }, []);

  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr");
    return guides.filter((g) =>
      (category === "Hepsi" || g.category === category) &&
      (!needle || g.title.toLocaleLowerCase("tr").includes(needle) || g.services.some((s) => s.toLocaleLowerCase("tr").includes(needle)))
    );
  }, [guides, category, query]);

  const byCategory = useMemo(() => {
    const m = new Map<string, GuideSummary[]>();
    for (const g of shown) m.set(g.category, [...(m.get(g.category) ?? []), g]);
    return [...m.entries()];
  }, [shown]);

  return (
    <div className="container">
      <header className="page-header">
        <h1>📚 Çözüm Rehberi</h1>
        <p className="lead">
          Satış ekibi için: bir sorunun ne olduğu, neden önemli olduğu, Mchttasarım&apos;ın nasıl çözdüğü, müşteriye nasıl anlatılacağı ve hangi hizmetin teklif edileceği.
          Sektör seçerseniz örnekler o sektöre göre uyarlanır.
        </p>
      </header>

      <div className="card">
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="g-sektor">Sektör (isteğe bağlı)</label>
            <select id="g-sektor" value={sectorId ?? ""} onChange={(e) => setSectorId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Genel (sektör seçilmedi)</option>
              {[...sectors].sort((a, b) => trSort(a.name, b.name)).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="g-ara">Sorun / hizmet ara</label>
            <input id="g-ara" type="search" placeholder="ör. HTTPS, yorum, kartvizit…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        <div className="chips" role="tablist" aria-label="Rehber kategorisi">
          <button className={`chip ${category === "Hepsi" ? "active" : ""}`} onClick={() => setCategory("Hepsi")}>Hepsi ({guides.length})</button>
          {categories.map((c) => (
            <button key={c} className={`chip ${category === c ? "active" : ""}`} onClick={() => setCategory(c)}>
              {c} ({guides.filter((g) => g.category === c).length})
            </button>
          ))}
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {byCategory.length === 0 && !error && <p className="muted">{guides.length === 0 ? "Rehberler yükleniyor…" : "Aramaya uyan rehber yok."}</p>}

      {byCategory.map(([cat, list]) => (
        <section key={cat}>
          <h2>{cat}</h2>
          <div className="guide-list">
            {list.map((g) => (
              <button key={g.id} className="guide-item" onClick={() => setOpenId(g.id)}>
                <strong>{g.title}</strong>
                <span className="muted small">{g.services.join(" · ")}</span>
              </button>
            ))}
          </div>
        </section>
      ))}

      {openId && <GuideModal guideId={openId} sectorId={sectorId ?? undefined} onClose={() => setOpenId(null)} />}
    </div>
  );
}
