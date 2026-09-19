"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GoogleApiState } from "@/lib/types";
import { formatIstanbul } from "../../_components/labels";

export default function ApiSettingsPage() {
  const [state, setState] = useState<GoogleApiState | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => api.getGoogleApi().then(setState).catch((e) => setMessage({ ok: false, text: e.message })), []);
  useEffect(() => { load(); }, [load]);

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name); setMessage(null);
    try { await fn(); } catch (e) { setMessage({ ok: false, text: (e as Error).message }); } finally { setBusy(null); }
  }

  return (
    <div className="container">
      <header className="page-header">
        <h1>🔌 API Ayarları</h1>
        <p className="lead">Google API'yi ileride bağlayabilirsiniz. API bağlansa bile mevcut veri kaynakları (Google Haritalar okuma, Bing Haritalar, web sitesi) çalışmaya devam eder; API yalnızca eksik bilgileri tamamlar ve kaynakları çapraz doğrular. API başarısız olursa sistem mevcut kaynaklarla devam eder.</p>
      </header>
      <section className="card" id="google-api-card">
        <h2 style={{ marginTop: 0 }}>Google API</h2>
        <p style={{ fontSize: 18 }}>Durum: <strong id="google-api-status">{state ? `${state.status_icon} ${state.status_label}` : "…"}</strong></p>
        {state && state.last_test_message && (
          <p className={state.last_test_ok ? "crm-ok small" : "error small"}>Son test ({formatIstanbul(state.last_test_at)}): {state.last_test_message}</p>
        )}
        <div className="form-field" style={{ maxWidth: 480 }}>
          <label htmlFor="api-key">API Key</label>
          <input id="api-key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)}
            placeholder={state?.has_key ? state.masked_key ?? "••••••••" : "Google Places API anahtarınızı yapıştırın"} />
          {state?.has_key && <span className="muted small">Kayıtlı anahtar: {state.masked_key} ({state.key_source === "environment" ? "sunucu ortamından" : "panelden kaydedildi"}). Güvenlik için anahtar tekrar gösterilmez.</span>}
        </div>
        <div className="actions">
          <button className="primary" disabled={!key.trim() || busy !== null}
            onClick={() => run("save", async () => { const s = await api.saveGoogleKey(key.trim()); setState(s); setKey(""); setMessage({ ok: true, text: "✓ API anahtarı şifreli olarak kaydedildi. Henüz Google'a istek atılmadı; bağlantıyı test edin." }); })}>
            {busy === "save" ? "Kaydediliyor…" : "API Key Kaydet"}
          </button>
          <button className="secondary" disabled={!state?.has_key || busy !== null}
            onClick={() => run("test", async () => { const r = await api.testGoogleApi(); setState(r.state); setMessage({ ok: r.ok, text: r.message }); })}>
            {busy === "test" ? "Test ediliyor…" : "Bağlantıyı Test Et"}
          </button>
          {state?.enabled ? (
            <button className="secondary" disabled={busy !== null} onClick={() => run("off", async () => { setState(await api.toggleGoogleApi(false)); setMessage({ ok: true, text: "API pasifleştirildi; sistem yalnızca mevcut kaynakları kullanıyor." }); })}>API'yi Pasifleştir</button>
          ) : (
            <button className="secondary" disabled={!state?.has_key || busy !== null}
              onClick={() => run("on", async () => { setState(await api.toggleGoogleApi(true)); setMessage({ ok: true, text: "✓ API aktifleştirildi: yeni analizlerde mevcut kaynaklara ek olarak kullanılacak." }); })}>
              API'yi Aktifleştir
            </button>
          )}
          {state?.has_key && state.key_source === "panel" && (
            <button className="secondary" disabled={busy !== null} onClick={() => { if (window.confirm("Kayıtlı API anahtarı silinsin mi?")) run("rm", async () => { setState(await api.removeGoogleKey()); setMessage({ ok: true, text: "Anahtar kaldırıldı." }); }); }}>Anahtarı Kaldır</button>
          )}
        </div>
        {message && <p className={message.ok ? "crm-ok" : "error"} role="status" id="api-message">{message.text}</p>}
        <p className="muted small">{state?.note}</p>
      </section>
      <section className="card">
        <h3>Şu anda kullanılan veri kaynakları</h3>
        <ul className="small">
          <li><strong>Google Haritalar</strong> (herkese açık sayfa, tarayıcı ile okuma) — firma keşfi ve İşletme Profili</li>
          <li><strong>Bing Haritalar</strong> — bağımsız ikinci dizin</li>
          <li><strong>Resmi web sitesi</strong> — gerçekten açılıp ölçülür</li>
          <li><strong>Sosyal medya</strong> — yalnızca site ve kayıtlarda doğrulanabilenler</li>
          <li><strong>Google Places API</strong> — {state?.status === "active" ? "AKTİF (tamamlayıcı)" : "bağlı değil / aktif değil"}</li>
        </ul>
        <p className="muted small">Erişilemeyen bilgi tahmin edilmez: "Doğrulanamadı" veya "ERİŞİLEMEDİ" olarak gösterilir. Google Arama CAPTCHA ile engelliyse aşılmaya çalışılmaz.</p>
      </section>
    </div>
  );
}
