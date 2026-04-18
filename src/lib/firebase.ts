import { getApp, getApps, initializeApp, type FirebaseApp, type FirebaseOptions } from 'firebase/app';
import { GoogleAuthProvider, browserLocalPersistence, getAuth, setPersistence, type Auth } from 'firebase/auth';
import { getStorage, type FirebaseStorage } from 'firebase/storage';

const firebaseConfig: FirebaseOptions = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const requiredFirebaseKeys = Object.entries(firebaseConfig)
  .filter(([, value]) => !value)
  .map(([key]) => key);

export const firebaseConfigured = requiredFirebaseKeys.length === 0;

let firebaseApp: FirebaseApp | null = null;
let firebaseAuth: Auth | null = null;
let firebaseStorage: FirebaseStorage | null = null;
let persistenceConfigured = false;

function assertFirebaseConfigured() {
  if (firebaseConfigured) {
    return;
  }
  throw new Error(
    `Firebase ist nicht konfiguriert. Fehlende Werte: ${requiredFirebaseKeys.join(', ')}.`,
  );
}

export function getFirebaseApp() {
  assertFirebaseConfigured();
  if (!firebaseApp) {
    firebaseApp = getApps().length ? getApp() : initializeApp(firebaseConfig);
  }
  return firebaseApp;
}

export function getFirebaseAuth() {
  if (!firebaseAuth) {
    firebaseAuth = getAuth(getFirebaseApp());
  }
  if (!persistenceConfigured) {
    persistenceConfigured = true;
    void setPersistence(firebaseAuth, browserLocalPersistence).catch((error) => {
      console.warn('Firebase Auth persistence konnte nicht gesetzt werden.', error);
    });
  }
  return firebaseAuth;
}

export function getFirebaseStorage() {
  if (!firebaseStorage) {
    firebaseStorage = getStorage(getFirebaseApp());
  }
  return firebaseStorage;
}

export const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ prompt: 'select_account' });
