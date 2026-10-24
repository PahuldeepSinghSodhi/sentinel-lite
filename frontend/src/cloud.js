import { createClient } from "@supabase/supabase-js";

export const CLOUD_MODE = import.meta.env.VITE_SENTINEL_MODE === "cloud";
export const supabase = CLOUD_MODE
  ? createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_ANON_KEY)
  : null;

export async function authHeaders() {
  const session = await requestSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

export async function requestSession() {
  if (!CLOUD_MODE) return null;
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session) throw new Error("Sign in to access your workspace.");
  return data.session;
}
