"use client";

// Arama ekranının state'ini (seçimler, sonuç listesi, filtre, sıralama, scroll konumu) korur.
//
// İki katman vardır:
// 1) Bellek (globalThis): sayfa içi gezinmede (liste → detay → geri) anında, API'ye yeniden sorgu atmadan yükler.
//    App Router'da `/` ve `/businesses/[id]` ayrı sayfalardır; detaya gidince `HomePage` unmount olur ve `useState` yok olur.
// 2) sessionStorage (sekmeye özel): TAM SAYFA YENİLEMEDE (F5, hata sonrası yeniden yükleme) bellek sıfırlanır; state buradan geri gelir.
//    Sekme kapanınca silinir, başka sekmeyle karışmaz; 12 saatten eski kayıtlar yok sayılır. Depolama kullanılamazsa (gizli mod, kota)
//    sessizce bellek katmanına düşülür — uygulama yine çalışır, yalnızca yenilemede state kaybolur.
//
// Hydration: sunucu HTML'i state'i bilmez. Bu yüzden tam sayfa yüklemede ilk render `initial` değerlerle yapılır, sessionStorage
// yalnızca hydration'dan SONRA (effect içinde) okunur; sayfa `useSessionReady()` true olana kadar yan etki (veri çekme/temizleme) yapmaz.

import { useCallback, useEffect, useRef, useState } from "react";

// Depo `globalThis` üzerinde tutulur: Next/Turbopack aynı modülü liste ve detay rotaları için ayrı kopyalar olarak yükleyebilir;
// bu durumda modül değişkenleri paylaşılmaz ve detaydaki "Geri" listeden gelindiğini bilemez.
type NavState = { fromList: boolean; scrollY: number; lockScroll: boolean };
type Shared = {
  __mchSearchStore?: Map<string, unknown>;
  __mchNav?: NavState;
  __mchSession?: { loaded: boolean; hydrated: boolean; reloadScroll: number | null; scrollChecked: boolean; scrollWriteEnabled: boolean };
};
const shared = globalThis as unknown as Shared;
const store: Map<string, unknown> = (shared.__mchSearchStore ??= new Map<string, unknown>());
const nav: NavState = (shared.__mchNav ??= {
  fromList: false, // kullanıcı işletme listesinden detaya mı gitti? (detaydaki "Geri" buna bakar)
  scrollY: 0, // liste scroll konumu
  lockScroll: false, // detaya giderken sayfa en üste sıçrayınca konumun ezilmesini engeller
});
const session = (shared.__mchSession ??= { loaded: false, hydrated: false, reloadScroll: null, scrollChecked: false, scrollWriteEnabled: true });

const isBrowser = () => typeof window !== "undefined";

// ------------------------------------------------------------------ sessionStorage katmanı
const PREFIX = "mch.s1.";
const SCROLL_KEY = "mch.s1.__scrollY";
const TTL_MS = 12 * 60 * 60 * 1000;
// Yenilemede saklanmaz: yeniden çekmesi ucuz ya da eskimesi zararlı olan değerler.
const EPHEMERAL = new Set(["search.regions", "search.sectors", "search.health", "dash.today", "dash.stale"]);

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null; // gizli mod / engellenmiş site verisi
  }
}

/** sessionStorage'daki kayıtları belleğe yükler (sayfa yüklemesi başına bir kez; bellekte zaten olan anahtarı ezmez). */
function loadSession(): void {
  if (!isBrowser() || session.loaded) return;
  session.loaded = true;
  const ss = storage();
  if (!ss) return;
  try {
    const stale: string[] = [];
    for (let i = 0; i < ss.length; i++) {
      const raw = ss.key(i);
      if (!raw || !raw.startsWith(PREFIX) || raw === SCROLL_KEY) continue;
      const key = raw.slice(PREFIX.length);
      if (store.has(key) || EPHEMERAL.has(key)) continue;
      try {
        const entry = JSON.parse(ss.getItem(raw) ?? "null") as { t: number; v: unknown } | null;
        if (!entry || Date.now() - entry.t > TTL_MS) stale.push(raw);
        else store.set(key, entry.v);
      } catch {
        stale.push(raw); // bozuk kayıt
      }
    }
    stale.forEach((k) => ss.removeItem(k));
  } catch {
    /* okunamadı: bellek katmanıyla devam */
  }
}

const pendingWrites = new Map<string, ReturnType<typeof setTimeout>>();

/** Değeri (kısa bir gecikmeyle, art arda yazımları birleştirerek) sessionStorage'a yazar. */
function persist(key: string): void {
  if (!isBrowser() || EPHEMERAL.has(key)) return;
  const previous = pendingWrites.get(key);
  if (previous) clearTimeout(previous);
  pendingWrites.set(
    key,
    setTimeout(() => {
      pendingWrites.delete(key);
      const ss = storage();
      if (!ss) return;
      try {
        ss.setItem(PREFIX + key, JSON.stringify({ t: Date.now(), v: store.get(key) }));
      } catch {
        // kota doldu: eski (artık yanlış) kaydı bırakmamak için siler; state bellekte yine çalışır
        try {
          ss.removeItem(PREFIX + key);
        } catch {
          /* yok say */
        }
      }
    }, 150)
  );
}

/** Sayfa kapanırken/yenilenirken bekleyen yazımlar kaybolmasın. */
if (isBrowser()) {
  window.addEventListener("pagehide", () => {
    for (const [key, timer] of pendingWrites) {
      clearTimeout(timer);
      pendingWrites.delete(key);
      const ss = storage();
      try {
        ss?.setItem(PREFIX + key, JSON.stringify({ t: Date.now(), v: store.get(key) }));
      } catch {
        try {
          ss?.removeItem(PREFIX + key);
        } catch {
          /* yok say */
        }
      }
    }
  });
}

/** Kök layout'taki küçük bileşen çağırır: bundan sonraki mount'lar hydration değil, sayfa içi gezinmedir. */
export function markHydrated(): void {
  session.hydrated = true;
}

// ------------------------------------------------------------------ hook'lar
/**
 * `useState` gibi çalışır; ama değer sayfalar arası (bellek) ve tam sayfa yenilemede (sessionStorage) korunur.
 * Aynı `key` ile geri gelince aynen yüklenir.
 */
export function usePersistentState<T>(key: string, initial: T): [T, (next: T | ((prev: T) => T)) => void] {
  const fromMemory = useRef(false);
  const [value, setValue] = useState<T>(() => {
    if (!isBrowser()) return initial;
    // Hydration'dan sonraki (sayfa içi gezinme) mount'larda sessionStorage da anında okunur; ilk yüklemede okunmaz (hydration uyumsuzluğu).
    if (session.hydrated) loadSession();
    if (store.has(key)) {
      fromMemory.current = true;
      return store.get(key) as T;
    }
    return initial;
  });

  // Tam sayfa yüklemede: hydration sonrası sessionStorage'dan geri yükle.
  useEffect(() => {
    if (fromMemory.current) return;
    loadSession();
    if (store.has(key)) setValue(store.get(key) as T);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        if (isBrowser()) {
          store.set(key, resolved);
          persist(key);
        }
        return resolved;
      });
    },
    [key]
  );
  return [value, set];
}

/**
 * Sayfadaki TÜM `usePersistentState` çağrılarından SONRA çağrılmalıdır. Geri yükleme tamamlanınca true olur (aynı commit'te,
 * yani true olduğu render'da geri yüklenen değerler de hazırdır). Yan etkiler (veri çekme, liste temizleme) bunu beklemelidir;
 * aksi halde ilk render'ın boş değerleriyle yanlış sorgu/temizleme yapılır.
 */
export function useSessionReady(): boolean {
  const [ready, setReady] = useState(() => isBrowser() && session.hydrated);
  useEffect(() => {
    loadSession();
    setReady(true);
  }, []);
  return ready;
}

// ------------------------------------------------------------------ gezinme / scroll
/** Listeden bir işletmenin detayına giderken çağrılır: scroll konumunu kaydeder ve "listeden geldi" işaretini koyar. */
export function markLeavingList(): void {
  if (!isBrowser()) return;
  nav.scrollY = window.scrollY;
  nav.lockScroll = true;
  nav.fromList = true;
  writeScroll(nav.scrollY);
}

/** Detay sayfası: kullanıcı listeden mi geldi? (Evetse "Geri" = router.back(); değilse listeye yönlendir.) */
export function cameFromList(): boolean {
  return nav.fromList;
}

function writeScroll(y: number): void {
  if (!session.scrollWriteEnabled) return;
  try {
    storage()?.setItem(SCROLL_KEY, JSON.stringify({ t: Date.now(), y }));
  } catch {
    /* yok say */
  }
}

/** Tam sayfa yükleme sonrası listeye ilk girişte, yenilemeden önceki scroll konumunu bir kez okur. */
function readSavedScroll(): number | null {
  try {
    const entry = JSON.parse(storage()?.getItem(SCROLL_KEY) ?? "null") as { t: number; y: number } | null;
    return entry && Date.now() - entry.t < TTL_MS && entry.y > 0 ? entry.y : null;
  } catch {
    return null;
  }
}

/**
 * Liste ekranı mount olduğunda çağrılır. Döndürür: geri dönülüyorsa (detaydan) kaydedilen scroll konumu, değilse null.
 * Ayrıca liste scroll konumunu sürekli izleyen dinleyiciyi kurar; kaldırma fonksiyonunu döndürür.
 */
export function enterList(): { restoreTo: number | null; stopTracking: () => void } {
  const returning = nav.fromList;
  const restoreTo = returning && nav.scrollY > 0 ? nav.scrollY : null;
  nav.fromList = false;
  nav.lockScroll = false;

  // Tam sayfa yükleme (yenileme): sayfa başlangıçta en üsttedir ve scroll olayları konumu 0 ile ezmesin diye yazım, geri yükleme bitene kadar kapalıdır.
  if (!session.scrollChecked) {
    session.scrollChecked = true;
    if (!returning) {
      session.reloadScroll = readSavedScroll();
      session.scrollWriteEnabled = session.reloadScroll === null;
    }
  }

  const onScroll = () => {
    if (nav.lockScroll) return;
    nav.scrollY = window.scrollY;
    writeScroll(window.scrollY);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  return { restoreTo, stopTracking: () => window.removeEventListener("scroll", onScroll) };
}

/** Yenileme sonrası geri yüklenecek scroll konumu (varsa, bir kez). Liste ekranda çizildikten sonra çağrılmalıdır. */
export function takeReloadScroll(): number | null {
  const y = session.reloadScroll;
  session.reloadScroll = null;
  if (y !== null) setTimeout(() => (session.scrollWriteEnabled = true), 800);
  return y;
}

/** Scroll konumunu geri yükler. Next kendi scroll sıfırlamasını yaptıysa kısa aralıklarla birkaç kez yeniden uygular. */
export function restoreScroll(y: number): void {
  const apply = () => {
    if (Math.abs(window.scrollY - y) > 4) window.scrollTo(0, y);
  };
  apply();
  requestAnimationFrame(apply);
  setTimeout(apply, 120);
  setTimeout(apply, 350);
}

// ------------------------------------------------------------------ dışarıdan güncelleme
/** Depoda tutulan işletme listelerinde (arama sonuçları, "bugün ara" paneli) bir işletmeyi günceller (ör. CRM durumu değişince). */
export function patchStoredBusiness(id: number, patch: Record<string, unknown>): void {
  loadSession(); // detay sayfası tam yüklendiyse depo henüz boştur; yamanın kaybolmaması için kayıtlı listeyi önce yükle
  for (const key of ["search.businesses", "dash.today"]) {
    const list = store.get(key);
    if (Array.isArray(list)) {
      store.set(key, list.map((b) => (b && (b as { id: number }).id === id ? { ...b, ...patch } : b)));
      persist(key);
    }
  }
  store.set("dash.stale", true);
}

/** "Bugünün potansiyel müşterileri" verisi eskidiyse (CRM değişti vb.) true döner ve işareti sıfırlar. */
export function consumeDashboardStale(): boolean {
  const stale = Boolean(store.get("dash.stale"));
  store.set("dash.stale", false);
  return stale;
}

/** Çıkış / kullanıcı değişimi: başka kullanıcının arama durumu (bellek + sessionStorage) görünmesin diye TÜMÜ temizlenir. */
export function clearSearchStore(): void {
  if (!isBrowser()) return;
  for (const timer of pendingWrites.values()) clearTimeout(timer);
  pendingWrites.clear();
  store.clear();
  nav.fromList = false;
  nav.scrollY = 0;
  session.reloadScroll = null;
  session.scrollWriteEnabled = true;
  const ss = storage();
  if (!ss) return;
  try {
    const keys: string[] = [];
    for (let i = 0; i < ss.length; i++) {
      const k = ss.key(i);
      if (k && k.startsWith("mch.")) keys.push(k);
    }
    keys.forEach((k) => ss.removeItem(k));
  } catch {
    /* yok say */
  }
}
