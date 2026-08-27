export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers ?? {});
  return fetch(input, {
    ...init,
    headers,
  });
}
