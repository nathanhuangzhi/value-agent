/** Email-code sign-in against the box's /auth and /me (tailscale serve paths). */
import { APP_TOKEN_HEADER, ApiError, BASE_URL } from './client';
import { authHeaders } from './session';

const ROOT = BASE_URL.replace(/\/reports$/, '');

export type User = { id: number; email: string; created_at: string };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${ROOT}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      cache: 'no-store',
      ...init,
      headers: { 'content-type': 'application/json', ...APP_TOKEN_HEADER, ...authHeaders(), ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError(0, `Network error reaching ${url}: ${e}`);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep the status text */ }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const authApi = {
  requestCode: (email: string) => req<Record<string, never>>('/auth/code', { method: 'POST', body: JSON.stringify({ email }) }),
  verify: (email: string, code: string) =>
    req<{ token: string; user: User }>('/auth/verify', { method: 'POST', body: JSON.stringify({ email, code }) }),
  me: () => req<User>('/me'),
  logout: () => req<Record<string, never>>('/auth/logout', { method: 'POST' }),
};
