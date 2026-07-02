// Thin typed HTTP client for the FastAPI backend.
//
// The base URL comes from the Electron preload bridge (`window.mrp.apiBaseUrl`),
// falling back to a Vite env var and finally the default loopback sidecar — so
// the same renderer runs in the packaged app and in a plain browser tab.

export function apiBaseUrl(): string {
  return (
    window.mrp?.apiBaseUrl ??
    (import.meta.env.VITE_API_BASE as string | undefined) ??
    "http://127.0.0.1:8000"
  );
}

/* Mutation listeners — the SWR cache subscribes so any successful write
   invalidates cached reads (registered from useApi to avoid an import cycle). */
type MutationListener = () => void;
const mutationListeners: MutationListener[] = [];
export function onApiMutation(listener: MutationListener): void {
  mutationListeners.push(listener);
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — GET ${path}`);
  }
  return (await res.json()) as T;
}

async function apiWrite<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }
  for (const listener of mutationListeners) listener();
  return (await res.json()) as T;
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiWrite<T>("POST", path, body);
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return apiWrite<T>("PUT", path, body);
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}${path}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — DELETE ${path}`);
  }
}
