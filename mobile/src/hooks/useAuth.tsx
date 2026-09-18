/**
 * Who is signed in. The token persists in AsyncStorage and is mirrored
 * into src/api/session.ts so the API clients can attach it. On launch the
 * stored token is validated against /me; a 401 clears it.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { authApi, type User } from '@/api/auth';
import { ApiError } from '@/api/client';
import { setSessionToken } from '@/api/session';

const KEY = 'auth_token_v1';

type Auth = {
  user: User | null;
  /** false until the stored token has been checked. */
  ready: boolean;
  requestCode: (email: string) => Promise<void>;
  verify: (email: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const token = await AsyncStorage.getItem(KEY);
        if (token) {
          setSessionToken(token);
          try {
            setUser(await authApi.me());
          } catch (e) {
            if (e instanceof ApiError && e.status === 401) {
              setSessionToken(null);
              await AsyncStorage.removeItem(KEY);
            }
            // offline: keep the token, the user stays "signed in" until proven otherwise
          }
        }
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const requestCode = useCallback(async (email: string) => {
    await authApi.requestCode(email);
  }, []);

  const verify = useCallback(async (email: string, code: string) => {
    const { token, user: u } = await authApi.verify(email, code);
    setSessionToken(token);
    await AsyncStorage.setItem(KEY, token);
    setUser(u);
  }, []);

  const signOut = useCallback(async () => {
    try { await authApi.logout(); } catch { /* best effort */ }
    setSessionToken(null);
    await AsyncStorage.removeItem(KEY);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, requestCode, verify, signOut }), [user, ready, requestCode, verify, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
