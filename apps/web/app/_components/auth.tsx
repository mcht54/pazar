"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { AuthUser } from "@/lib/types";
import { clearSearchStore } from "./search-store";

// Oturum: sunucu tarafı (HttpOnly çerez). Sayfa yenilenince /api/auth/me ile geri yüklenir. Yetki kontrolünün asıl sınırı SUNUCUDADIR;
// buradaki `can` yalnızca menü/düğmeleri gizlemek içindir.
interface AuthValue {
  user: AuthUser | null;
  loading: boolean;
  /** Oturum denetimi sunucuya ulaşamadıysa (ağ/zaman aşımı/5xx) açıklama; 401 (giriş yapılmamış) hata sayılmaz. */
  authError: string | null;
  can: (permission: string) => boolean;
  login: (identifier: string, password: string, remember?: boolean) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (user: AuthUser | null) => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth yalnızca AuthProvider içinde kullanılabilir");
  return value;
}

const LAST_USER_KEY = "mch.lastUser";

function rememberUser(user: AuthUser | null) {
  // Başka bir kullanıcı giriş yaptıysa önceki kullanıcının arama durumu temizlenir.
  try {
    const previous = sessionStorage.getItem(LAST_USER_KEY);
    if (user && previous && previous !== String(user.id)) clearSearchStore();
    if (user) sessionStorage.setItem(LAST_USER_KEY, String(user.id));
  } catch {
    /* depolama yok */
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  const setUser = useCallback((next: AuthUser | null) => {
    rememberUser(next);
    setUserState(next);
  }, []);

  // Oturum denetimi HER durumda sonlanır (api.me zaman aşımına sahiptir): giriş yok → login ekranı; sunucu sorunu → hata + "Tekrar dene".
  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
      setAuthError(null);
    } catch (err) {
      setUser(null);
      const unauthenticated = err instanceof ApiError && err.status === 401;
      setAuthError(unauthenticated ? null : err instanceof ApiError && err.status !== 0 ? `Oturum durumu alınamadı (sunucu yanıtı: ${err.status}).` : (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [setUser]);

  useEffect(() => {
    refresh();
    const onUnauthorized = () => {
      setUserState(null);
      setAuthError(null);
    };
    const onPasswordChange = () => refresh();
    window.addEventListener("mch:unauthorized", onUnauthorized);
    window.addEventListener("mch:password-change", onPasswordChange);
    return () => {
      window.removeEventListener("mch:unauthorized", onUnauthorized);
      window.removeEventListener("mch:password-change", onPasswordChange);
    };
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      authError,
      can: (permission) => !!user && user.permissions.includes(permission),
      login: async (identifier, password, remember = false) => {
        const u = await api.login(identifier, password, remember);
        setAuthError(null);
        setUser(u);
        return u;
      },
      logout: async () => {
        try {
          await api.logout();
        } finally {
          clearSearchStore();
          setUserState(null);
          setAuthError(null);
          try {
            sessionStorage.removeItem(LAST_USER_KEY);
          } catch {
            /* yok say */
          }
        }
      },
      refresh,
      setUser,
    }),
    [user, loading, authError, refresh, setUser]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Korumalı alan: giriş yapmamışsa /login'e; geçici şifreyle girmişse şifre değiştirme ekranına; yönetim sayfalarında yönetici değilse engel ekranı. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, authError, refresh } = useAuth();
  const [retrying, setRetrying] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const onLogin = pathname === "/login";
  const onPublic = onLogin || pathname === "/sifremi-unuttum" || pathname === "/sifre-belirle"; // giriş gerektirmeyen sayfalar
  const onProfile = pathname === "/profil";

  useEffect(() => {
    if (loading) return;
    if (!user && !onPublic) {
      if (!authError) router.replace("/login"); // sunucu hatasında login'e atılmaz: kullanıcı oturum açmış olabilir, hata gösterilir
    } else if (user && onLogin) router.replace(user.must_change_password ? "/profil" : "/");
    else if (user?.must_change_password && !onProfile) router.replace("/profil");
  }, [loading, user, authError, onLogin, onPublic, onProfile, router]);

  if (loading) return <div className="container"><p className="muted" role="status">Oturum kontrol ediliyor…</p></div>;
  if (onPublic) return <>{children}</>;
  if (!user && authError) {
    return (
      <div className="container">
        <div className="card" role="alert">
          <h1>⚠️ Sunucuya ulaşılamadı</h1>
          <p>{authError}</p>
          <p className="muted small">Oturumunuz kapatılmadı. Bağlantı sorunu geçince tekrar deneyebilirsiniz.</p>
          <button className="primary" type="button" disabled={retrying} onClick={() => { setRetrying(true); void refresh().finally(() => setRetrying(false)); }}>{retrying ? "Deneniyor…" : "Tekrar dene"}</button>
        </div>
      </div>
    );
  }
  if (!user) return null;
  if (user.must_change_password && !onProfile) return null;
  if (pathname.startsWith("/yonetim") && user.role !== "yonetici") {
    return (
      <div className="container">
        <div className="card">
          <h1>⛔ Erişim yetkiniz yok</h1>
          <p>Bu sayfa yalnızca yönetici rolündeki kullanıcılar içindir.</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
