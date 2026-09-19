"use client";

import { useEffect } from "react";
import { markHydrated } from "./search-store";

/** Kök layout'ta bir kez çalışır: hydration bittikten sonraki mount'lar sayfa içi gezinme sayılır (bkz. search-store.ts). */
export default function SessionBootstrap() {
  useEffect(() => {
    markHydrated();
  }, []);
  return null;
}
