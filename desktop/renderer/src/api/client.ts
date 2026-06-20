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

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — GET ${path}`);
  }
  return (await res.json()) as T;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    method: "POST",
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
  return (await res.json()) as T;
}
