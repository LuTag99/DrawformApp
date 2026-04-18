import { firebaseConfigured, getFirebaseAuth } from '../lib/firebase';

async function getAccessToken(): Promise<string | null> {
  if (!firebaseConfigured) {
    return null;
  }
  const currentUser = getFirebaseAuth().currentUser;
  if (!currentUser) {
    return null;
  }
  return currentUser.getIdToken();
}

export async function authorizedFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers ?? {});
  const token = await getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(input, {
    ...init,
    headers,
  });
}
