// Notifications carry the credentials used by the failed request, never just a status.
const listeners = new Set();
const deniedCodes = new Set(["session_invalid", "account_unverified", "invite_required"]);

export function accountIdentity(session) {
  return session?.user?.id
    ? JSON.stringify([session.user.id, (session.user.email || "").trim().toLowerCase()])
    : "";
}

export function subscribeAccessFailure(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notifyAccessFailure(error, session) {
  if (!session || !deniedCodes.has(error.code)) return;
  for (const listener of listeners) listener({ error, session });
}
