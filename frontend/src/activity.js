import { useSyncExternalStore } from "react";

let pending = 0;
const listeners = new Set();
const subscribe = (listener) => { listeners.add(listener); return () => listeners.delete(listener); };
const snapshot = () => pending;

export function useRequestActivity() {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export async function trackActivity(work, silent = false) {
  const change = (amount) => { pending += amount; for (const listener of listeners) listener(); };
  if (!silent) change(1);
  try { return await work(); }
  finally { if (!silent) change(-1); }
}
