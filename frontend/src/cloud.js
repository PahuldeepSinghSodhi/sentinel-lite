import { createClient } from "@supabase/supabase-js";
import { createCognitoClient } from "./cognito";

export const CLOUD_MODE = import.meta.env.VITE_SENTINEL_MODE === "cloud";
export const CLOUD_PROVIDER = import.meta.env.VITE_CLOUD_PROVIDER || "supabase";
if (!["supabase", "aws"].includes(CLOUD_PROVIDER)) throw new Error("Unknown cloud provider");
export const supabase = CLOUD_MODE
  ? CLOUD_PROVIDER === "aws" ? createCognitoClient({ region: import.meta.env.VITE_AWS_REGION,
    poolId: import.meta.env.VITE_COGNITO_USER_POOL_ID, clientId: import.meta.env.VITE_COGNITO_CLIENT_ID })
    : createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_ANON_KEY)
  : null;

export async function authHeaders() {
  const session = await requestSession();
  return session ? { Authorization: `Bearer ${session.identity_token || session.access_token}` } : {};
}

export async function requestSession() {
  if (!CLOUD_MODE) return null;
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  if (!data.session) throw new Error("Sign in to access your workspace.");
  return data.session;
}
