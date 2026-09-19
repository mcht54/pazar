"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "./auth";

function Dropdown({ label, children, id }: { label: React.ReactNode; children: React.ReactNode; id: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  return (
    <div className="nav-dropdown" ref={ref}>
      <button className="nav-drop-btn" id={id} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{label} ▾</button>
      {open && <div className="nav-drop-menu" role="menu">{children}</div>}
    </div>
  );
}

export default function AppHeader() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const admin = user?.role === "yonetici";

  return (
    <header className="app-header">
      <div className="app-header-inner">
        <strong className="app-brand">Mchttasarım Satış Operasyon</strong>
        {user && !user.must_change_password && (
          <nav aria-label="Ana menü">
            <Link href="/">🎯 Satış Paneli</Link>
            <Link href="/crm">📋 CRM</Link>
            <Link href="/rehber">📚 Çözüm Rehberi</Link>
            {admin && (
              <Dropdown id="menu-yonetim" label="⚙️ Yönetim">
                <Link href="/yonetim/kullanicilar" role="menuitem">👥 Kullanıcı Yönetimi</Link>
                <Link href="/yonetim/api" role="menuitem">🔌 API Ayarları</Link>
                <Link href="/yonetim/eposta" role="menuitem">✉️ E-posta Ayarları</Link>
                <Link href="/yonetim/fiyat" role="menuitem">💰 Hizmet ve Fiyat Ayarları</Link>
                <Link href="/yonetim/aktivite" role="menuitem">🕘 Personel Aktiviteleri</Link>
                <Link href="/yonetim/rapor" role="menuitem">📊 Personel Raporu</Link>
              </Dropdown>
            )}
          </nav>
        )}
        {user && (
          <Dropdown id="menu-profil" label={<>👤 {user.name} <span className="role-chip" title={user.role_label}>{user.role_icon} {user.role_label}</span></>}>
            <Link href="/profil" role="menuitem">🔑 Şifre Değiştir</Link>
            <button
              role="menuitem"
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
            >
              🚪 Çıkış Yap
            </button>
          </Dropdown>
        )}
      </div>
    </header>
  );
}
