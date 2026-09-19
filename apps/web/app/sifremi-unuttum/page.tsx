"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      // Yanıt e-posta kayıtlı olsun olmasın aynıdır (hesap keşfi yapılamaz).
      setMessage((await api.forgotPassword(email.trim())).message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit} aria-label="Şifremi unuttum formu">
        <h1>🔑 Şifremi Unuttum</h1>
        <p className="muted small">E-posta adresinizi girin. Hesabınız varsa şifre belirleme bağlantısı gönderilir (bağlantı tek kullanımlık ve 60 dakika geçerlidir).</p>
        <div className="form-field">
          <label htmlFor="forgot-email">E-posta</label>
          <input id="forgot-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </div>
        {message && <p className="crm-ok" role="status" id="forgot-message">{message}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy || !email}>{busy ? "Gönderiliyor…" : "Bağlantı İste"}</button>
        <p className="small"><Link href="/login">← Giriş sayfasına dön</Link></p>
      </form>
    </div>
  );
}
