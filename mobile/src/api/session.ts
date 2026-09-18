/**
 * The signed-in session, readable synchronously by every API client.
 * `useAuth` (src/hooks/useAuth.tsx) owns the value; this module just holds
 * it so request helpers can add `Authorization: Bearer …` without hooks.
 */
let token: string | null = null;

export function setSessionToken(t: string | null) {
  token = t;
}

export function getSessionToken(): string | null {
  return token;
}

/** Headers for the authenticated services (/ai, /watchlist, /auth, /me). */
export function authHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}
