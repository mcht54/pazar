"use client";

import { useState } from "react";
import type { Business } from "@/lib/types";
import { Modal } from "./modal";
import { whatsappUrl } from "./labels";

/** MarkaKarnem tanıtımı: kare görsel + işletmenin adıyla doldurulmuş ücretsiz analiz bağlantısı.
 *  Bağlantı ve metin kuralları sunucudaki services/sales/scripts.py ile aynıdır (k=pazar → MarkaKarnem panelinde kaynak sayılır). */
export const MARKAKARNEM_IMAGE = "/markakarnem-kare.jpg";

export function markakarnemLink(name: string, regionLabel?: string | null): string {
  const place = regionLabel ? regionLabel.split(",")[0] : "";
  const q = `${name} ${place}`.replace(/[&#?%+/=\\]/g, " ").split(/\s+/).filter(Boolean).join("+");
  return `https://markakarnem.com.tr/analiz?q=${q}&k=pazar`;
}

export function markakarnemText(name: string, regionLabel?: string | null): string {
  return "Merhaba, işletmenizin dijital karnesini 1 dakikada ücretsiz görebilirsiniz: web siteniz, Google profiliniz ve Instagram'ınız "
    + "52 kontrolle ölçülür, yakınınızdaki rakiplerle kıyaslanır. Kart bilgisi gerekmez.\n"
    + `👉 ${markakarnemLink(name, regionLabel)}`;
}

/** Görsel + metin. Telefonda "Paylaş" görseli ve metni birlikte WhatsApp'a gönderir; bilgisayarda görsel indirilir, metin kopyalanır. */
export function MarkaKarnemShare({ text, phone, compact = false }: { text: string; phone?: string | null; compact?: boolean }) {
  const [msg, setMsg] = useState<string | null>(null);
  const wa = whatsappUrl(phone);

  async function copy() {
    try { await navigator.clipboard.writeText(text); setMsg("✓ Metin kopyalandı"); } catch { setMsg("Metin kopyalanamadı; elle seçip kopyalayın."); }
  }

  async function share() {
    try {
      const blob = await (await fetch(MARKAKARNEM_IMAGE)).blob();
      const file = new File([blob], "markakarnem.jpg", { type: blob.type || "image/jpeg" });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], text });
        return;
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
    }
    await copy();
    setMsg("Bu cihaz görselli paylaşımı desteklemiyor: metin kopyalandı, görseli “Görseli indir” ile alıp mesaja ekleyin.");
  }

  return (
    <div className={`mk-share${compact ? " mk-compact" : ""}`} data-testid="markakarnem-share">
      <img src={MARKAKARNEM_IMAGE} alt="MarkaKarnem: İşletmenizin dijital karnesi 1 dakikada, ücretsiz" width={1080} height={1080} loading="lazy" />
      <div className="mk-side">
        <div className="label-cap">MarkaKarnem tanıtımı</div>
        <p className="small muted" style={{ margin: "4px 0 10px" }}>Görseli mesajla birlikte gönderin. Bağlantı işletmenin adıyla açılır; analiz ücretsizdir.</p>
        <div className="actions" style={{ flexWrap: "wrap" }}>
          <button className="primary" onClick={share}>📤 Görsel + metni paylaş</button>
          <a className="secondary btn-link" href={MARKAKARNEM_IMAGE} download="markakarnem.jpg">⬇️ Görseli indir</a>
          <button className="secondary" onClick={copy}>📋 Metni kopyala</button>
          {wa && <a className="secondary btn-link" href={`${wa}?text=${encodeURIComponent(text)}`} target="_blank" rel="noreferrer">💬 WhatsApp'ta aç</a>}
        </div>
        {wa && <p className="small muted" style={{ margin: "8px 0 0" }}>“WhatsApp'ta aç” yalnızca metni taşır; görseli ayrıca ekleyin.</p>}
        {msg && <p className="small" role="status" style={{ margin: "8px 0 0" }}>{msg}</p>}
      </div>
    </div>
  );
}

/** Hızlı eylemler çubuğundaki "MarkaKarnem" butonu: tek başına gönderilecek tanıtım mesajı. */
export function MarkaKarnemButton({ business }: { business: Pick<Business, "name" | "region_label" | "phone"> }) {
  const [open, setOpen] = useState(false);
  const text = markakarnemText(business.name, business.region_label);
  return (
    <>
      <button className="qa-btn" onClick={() => setOpen(true)} title="İşletmeye ücretsiz MarkaKarnem analizini gönderin">📊 MarkaKarnem</button>
      {open && (
        <Modal title={`MarkaKarnem — ${business.name}`} onClose={() => setOpen(false)}>
          <pre className="script-box">{text}</pre>
          <MarkaKarnemShare text={text} phone={business.phone} />
        </Modal>
      )}
    </>
  );
}
