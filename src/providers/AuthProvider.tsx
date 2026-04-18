import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  EmailAuthProvider,
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  reauthenticateWithCredential,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  updatePassword,
  updateProfile as updateFirebaseProfile,
  type User,
} from 'firebase/auth';
import { AuthContext } from './AuthContext';
import type { AuthContextValue, AuthUser } from './authTypes';
import { firebaseConfigured, getFirebaseAuth, googleProvider } from '../lib/firebase';

const defaultHighlights = [
  'Firebase Auth aktiv',
  'Storage je Benutzer',
  'Co-Pilot assistiert',
];

function mapAuthError(error: unknown) {
  const code = typeof error === 'object' && error && 'code' in error ? String(error.code) : '';
  switch (code) {
    case 'auth/email-already-in-use':
      return 'Diese E-Mail wird bereits verwendet.';
    case 'auth/invalid-email':
      return 'Bitte eine gueltige E-Mail eingeben.';
    case 'auth/user-not-found':
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
      return 'Ungueltige Zugangsdaten.';
    case 'auth/weak-password':
      return 'Das Passwort muss mindestens 6 Zeichen haben.';
    case 'auth/popup-closed-by-user':
      return 'Google-Anmeldung wurde geschlossen.';
    case 'auth/popup-blocked':
      return 'Popup wurde blockiert. Bitte Popups fuer diese Seite erlauben.';
    case 'auth/requires-recent-login':
      return 'Bitte erneut anmelden, bevor du sicherheitsrelevante Daten aenderst.';
    case 'auth/operation-not-allowed':
      return 'Diese Anmeldemethode ist in Firebase noch nicht aktiviert.';
    default:
      return (error as Error)?.message ?? 'Authentifizierung fehlgeschlagen.';
  }
}

function buildUser(user: User): AuthUser {
  const providers = user.providerData
    .map((entry) => entry.providerId)
    .filter(Boolean)
    .map((providerId) => {
      if (providerId === 'password') {
        return 'password';
      }
      if (providerId === 'google.com') {
        return 'google';
      }
      return providerId;
    });
  return {
    uid: user.uid,
    email: user.email ?? 'unknown@drawform.local',
    displayName: user.displayName ?? undefined,
    avatarUrl: user.photoURL ?? undefined,
    highlights: defaultHighlights,
    providers: providers.length ? providers : ['password'],
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  // Initialzustand bewusst aus firebaseConfigured ableiten: bei aktiver
  // Firebase-Konfig starten wir mit loading=true und warten auf den ersten
  // onAuthStateChanged-Callback; ohne Konfig gibt es nichts zu laden.
  const [loading, setLoading] = useState(firebaseConfigured);

  useEffect(() => {
    if (!firebaseConfigured) {
      return;
    }
    const auth = getFirebaseAuth();
    const unsubscribe = onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser ? buildUser(nextUser) : null);
      setLoading(false);
    });
    return unsubscribe;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    if (!firebaseConfigured) {
      return 'Firebase ist noch nicht konfiguriert.';
    }
    if (!email.trim()) {
      return 'Bitte E-Mail eingeben.';
    }
    try {
      await signInWithEmailAndPassword(getFirebaseAuth(), email.trim(), password);
      return null;
    } catch (error) {
      return mapAuthError(error);
    }
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    if (!firebaseConfigured) {
      return 'Firebase ist noch nicht konfiguriert.';
    }
    if (!email.trim()) {
      return 'Die E-Mail darf nicht leer sein.';
    }
    if (password.length < 6) {
      return 'Das Passwort muss mindestens 6 Zeichen haben.';
    }
    try {
      await createUserWithEmailAndPassword(getFirebaseAuth(), email.trim(), password);
      return null;
    } catch (error) {
      return mapAuthError(error);
    }
  }, []);

  const loginWithGoogle = useCallback(async () => {
    if (!firebaseConfigured) {
      return 'Firebase ist noch nicht konfiguriert.';
    }
    try {
      await signInWithPopup(getFirebaseAuth(), googleProvider);
      return null;
    } catch (error) {
      return mapAuthError(error);
    }
  }, []);

  const resetPassword = useCallback(async (email: string) => {
    if (!firebaseConfigured) {
      return 'Firebase ist noch nicht konfiguriert.';
    }
    if (!email.trim()) {
      return 'Bitte E-Mail eingeben.';
    }
    try {
      await sendPasswordResetEmail(getFirebaseAuth(), email.trim());
      return 'Wir haben Ihnen eine E-Mail zum Zuruecksetzen gesendet.';
    } catch (error) {
      return mapAuthError(error);
    }
  }, []);

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
      if (!firebaseConfigured) {
        return 'Firebase ist noch nicht konfiguriert.';
      }
      const auth = getFirebaseAuth();
      const currentUser = auth.currentUser;
      if (!currentUser) {
        return 'Kein angemeldeter Benutzer.';
      }
      try {
        if (avatarUrl !== undefined) {
          await updateFirebaseProfile(currentUser, {
            photoURL: avatarUrl.trim() || null,
          });
        }
        if (newPassword) {
          const canChangePassword = currentUser.providerData.some(
            (entry) => entry.providerId === 'password',
          );
          if (!canChangePassword) {
            return 'Passwortaenderung ist nur fuer E-Mail/Passwort-Konten verfuegbar.';
          }
          if (!currentPassword) {
            return 'Bitte aktuelles Passwort angeben.';
          }
          if (!currentUser.email) {
            return 'Zum Passwortwechsel fehlt die E-Mail am Konto.';
          }
          const credential = EmailAuthProvider.credential(
            currentUser.email,
            currentPassword,
          );
          await reauthenticateWithCredential(currentUser, credential);
          await updatePassword(currentUser, newPassword);
        }
        setUser(buildUser(currentUser));
        return null;
      } catch (error) {
        return mapAuthError(error);
      }
    },
    [],
  );

  const logout = useCallback(() => {
    if (!firebaseConfigured) {
      setUser(null);
      return;
    }
    void signOut(getFirebaseAuth()).catch((error) => {
      console.error('Logout fehlgeschlagen', error);
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      firebaseConfigured,
      login,
      register,
      loginWithGoogle,
      resetPassword,
      updateProfile,
      logout,
    }),
    [
      user,
      loading,
      login,
      register,
      loginWithGoogle,
      resetPassword,
      updateProfile,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
