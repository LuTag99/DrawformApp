import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { AuthContext } from './AuthContext';
import type { AuthContextValue, AuthUser, Credentials } from './authTypes';

const STORAGE_KEY = 'drawform-auth';
const defaultHighlights = [
  'AI Monitoring aktiv',
  'Glas-Flows bereit',
  'Co-Pilot assistiert',
];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) {
        setLoading(false);
        return;
      }
      const parsed = JSON.parse(stored) as {
        user: AuthUser | null;
        credentials: Credentials | null;
      };
      setUser(parsed.user);
      setCredentials(parsed.credentials);
    } catch (error) {
      console.error('Auth parse error', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const payload = JSON.stringify({ user, credentials });
    localStorage.setItem(STORAGE_KEY, payload);
  }, [user, credentials]);

  const ensureUserFromCredentials = useCallback(
    (data: Credentials): AuthUser => ({
      email: data.email,
      avatarUrl: data.avatarUrl,
      highlights: data.highlights?.length ? data.highlights : defaultHighlights,
    }),
    [],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      if (!credentials) {
        return 'Es ist kein Benutzer registriert.';
      }
      if (!email.trim()) {
        return 'Bitte E-Mail eingeben.';
      }
      const matches =
        credentials.email === email.trim() && credentials.password === password;
      if (!matches) {
        return 'Ungültige Zugangsdaten.';
      }
      setUser(ensureUserFromCredentials(credentials));
      return null;
    },
    [credentials, ensureUserFromCredentials],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      if (!email.trim()) {
        return 'Die E-Mail darf nicht leer sein.';
      }
      if (password.length < 6) {
        return 'Das Passwort muss mindestens 6 Zeichen haben.';
      }
      const setup: Credentials = {
        email: email.trim(),
        password,
        avatarUrl: credentials?.avatarUrl,
        highlights: credentials?.highlights ?? defaultHighlights,
      };
      setCredentials(setup);
      setUser(ensureUserFromCredentials(setup));
      return null;
    },
    [credentials?.avatarUrl, credentials?.highlights, ensureUserFromCredentials],
  );

  const resetPassword = useCallback(
    async (email: string) => {
      if (!credentials) {
        return 'Es ist kein Benutzer registriert.';
      }
      if (credentials.email !== email.trim()) {
        return 'Diese E-Mail ist unbekannt.';
      }
      return 'Wir haben Ihnen eine E-Mail zum Zurücksetzen gesendet.';
    },
    [credentials],
  );

  const updateProfile = useCallback(
    async ({
      avatarUrl,
      currentPassword,
      newPassword,
    }: {
      avatarUrl?: string;
      currentPassword?: string;
      newPassword?: string;
    }) => {
      if (!credentials) {
        return 'Kein angemeldeter Benutzer.';
      }
      const updatedCredentials = { ...credentials };
      if (avatarUrl !== undefined) {
        updatedCredentials.avatarUrl = avatarUrl.trim();
      }
      if (newPassword) {
        if (!currentPassword) {
          return 'Bitte aktuelles Passwort angeben.';
        }
        if (credentials.password !== currentPassword) {
          return 'Das aktuelle Passwort ist falsch.';
        }
        if (newPassword.length < 6) {
          return 'Das neue Passwort muss mindestens 6 Zeichen haben.';
        }
        updatedCredentials.password = newPassword;
      }
      setCredentials(updatedCredentials);
      setUser(ensureUserFromCredentials(updatedCredentials));
      return null;
    },
    [credentials, ensureUserFromCredentials],
  );

  const logout = useCallback(() => {
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login,
      register,
      resetPassword,
      updateProfile,
      logout,
    }),
    [user, loading, login, register, resetPassword, updateProfile, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
