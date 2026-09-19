"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EmailState } from "@/lib/types";
import { formatIstanbul } from "../../_components/labels";

export default function EmailSettingsPage() {
  const [state, setState] = useState<EmailState | null>(null);
  const [form, setForm] = useState({ host: "", port: "587", username: "", password: "", from_name: "Mchttasarım", from_email: "", security: "tls" });
  const [testTo, setTestTo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => api.getEmailSettings().then((s) => {
    setState(s);
    if (s.configured) setForm((f) => ({ ...f, host: s.host ?? "", port: String(s.port ?? 587), username: s.username ?? "", from_name: s.from_name ?? "", from_email: s.from_email ?? "", security: s.security, password: "" }));
  }).catch((e) => setMessage({ ok: false, text: e.message })), []);
  useEffect(() => { load(); }, [load]);

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name); setMessage(null);
    try { await fn(); } catch (e) { setMessage({ ok: false, text: (e as Error).message }); } finally { setBusy(null); }
  }
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="container">
      <header className="page-header">
        <h1>✉️ E-posta Ayarları</h1>
        <p className="lead">Yeni kullanıcı davetleri ve “Şifremi unuttum” bağlantıları bu SMTP ayarıyla gönderilir. E-postayla asla düz şifre gönderilmez; yalnızca tek kullanımlık, süreli bir şifre belirleme bağlantısı gider. SMTP şifresi şifreli saklanır ve bir daha gösterilmez.</p>
      </header>
      <section className="card" id="email-card">
        <p style={{ fontSize: 18 }}>Durum: <strong id="email-status">{state ? `${state.status_icon} ${state.status_label}` : "…"}</strong></p>
        {state?.last_test_message && <p className={state.last_test_ok ? "crm-ok small" : "error small"}>Son test ({formatIstanbul(state.last_test_at)}): {state.last_test_message}</p>}
        <div className="form-row">
          <div className="form-field"><label htmlFor="smtp-host">SMTP sunucu</label><input id="smtp-host" value={form.host} onChange={(e) => set("host", e.target.value)} placeholder="smtp.example.com" /></div>
          <div className="form-field narrow"><label htmlFor="smtp-port">Port</label><input id="smtp-port" inputMode="numeric" value={form.port} onChange={(e) => set("port", e.target.value)} /></div>
          <div className="form-field"><label htmlFor="smtp-sec">Güvenlik</label>
            <select id="smtp-sec" value={form.security} onChange={(e) => set("security", e.target.value)}>
              {(state?.securities ?? [{ key: "tls", label: "TLS (STARTTLS, genellikle 587)" }]).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
        </div>
        <div className="form-row">
          <div className="form-field"><label htmlFor="smtp-user">Kullanıcı adı</label><input id="smtp-user" autoComplete="off" value={form.username} onChange={(e) => set("username", e.target.value)} /></div>
          <div className="form-field"><label htmlFor="smtp-pass">Şifre</label>
            <input id="smtp-pass" type="password" autoComplete="new-password" value={form.password} onChange={(e) => set("password", e.target.value)} placeholder={state?.has_password ? `${state.masked_password} (değiştirmek için yazın)` : ""} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-field"><label htmlFor="smtp-from-name">Gönderen adı</label><input id="smtp-from-name" value={form.from_name} onChange={(e) => set("from_name", e.target.value)} /></div>
          <div className="form-field"><label htmlFor="smtp-from">Gönderen e-posta</label><input id="smtp-from" type="email" value={form.from_email} onChange={(e) => set("from_email", e.target.value)} /></div>
        </div>
        {form.security === "none" && <p className="unverified small">⚠️ Şifresiz bağlantı yalnızca yerel/test sunucusu içindir; gerçek kullanımda TLS veya SSL seçin.</p>}
        <div className="actions">
          <button className="primary" disabled={busy !== null || !form.host || !form.from_email}
            onClick={() => run("save", async () => { setState(await api.saveEmailSettings({ host: form.host, port: Number(form.port), username: form.username || null, password: form.password || null, from_name: form.from_name, from_email: form.from_email, security: form.security })); set("password", ""); setMessage({ ok: true, text: "✓ Ayarlar kaydedildi. Aktifleştirmek için test e-postası gönderin." }); })}>
            {busy === "save" ? "Kaydediliyor…" : "Ayarları Kaydet"}
          </button>
        </div>
        <hr />
        <div className="form-row">
          <div className="form-field"><label htmlFor="smtp-test-to">Test alıcısı</label><input id="smtp-test-to" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="ornek@firma.com" /></div>
        </div>
        <div className="actions">
          <button className="secondary" disabled={busy !== null || !state?.configured || !testTo}
            onClick={() => run("test", async () => { const r = await api.testEmailSettings(testTo); setState(r.state); setMessage({ ok: r.ok, text: r.message }); })}>
            {busy === "test" ? "Gönderiliyor…" : "Test E-postası Gönder"}
          </button>
          {state?.enabled ? (
            <button className="secondary" disabled={busy !== null} onClick={() => run("off", async () => { setState(await api.toggleEmailSettings(false)); setMessage({ ok: true, text: "E-posta gönderimi pasifleştirildi." }); })}>Pasifleştir</button>
          ) : (
            <button className="secondary" id="email-enable" disabled={busy !== null || !["tested"].includes(state?.status ?? "")}
              onClick={() => run("on", async () => { setState(await api.toggleEmailSettings(true)); setMessage({ ok: true, text: "✓ E-posta aktifleştirildi." }); })}>
              Aktifleştir
            </button>
          )}
        </div>
        {!state?.enabled && state?.status !== "tested" && <p className="muted small">Aktifleştirmek için önce başarılı bir test e-postası gönderilmelidir.</p>}
        {message && <p className={message.ok ? "crm-ok" : "error"} role="status" id="email-message">{message.text}</p>}
      </section>
    </div>
  );
}
