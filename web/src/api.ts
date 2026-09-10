import type {
  BatchRowState,
  BatchState,
  DeclaredFields,
  SessionState,
  VerifyResponse,
} from "./types";

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return res.json() as Promise<T>;
}

export async function verify(
  fields: DeclaredFields,
  images: { file: File; role: string }[],
): Promise<VerifyResponse> {
  const form = new FormData();
  form.append("application", JSON.stringify(fields));
  for (const { file, role } of images) {
    form.append("images", file);
    form.append("roles", role);
  }
  return unwrap<VerifyResponse>(
    await fetch("/api/verify", { method: "POST", body: form }),
  );
}

export async function getSession(id: string): Promise<SessionState> {
  return unwrap<SessionState>(await fetch(`/api/sessions/${id}`));
}

export async function recordDecision(
  id: string,
  checkId: string,
  decision: "accept" | "reject",
): Promise<SessionState> {
  await unwrap(
    await fetch(`/api/sessions/${id}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ check_id: checkId, decision }),
    }),
  );
  return getSession(id);
}

export async function finalize(
  id: string,
  action: "approve" | "reject" | "request_image",
): Promise<SessionState> {
  await unwrap(
    await fetch(`/api/sessions/${id}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }),
  );
  return getSession(id);
}

// ---- batch --------------------------------------------------------------

export const MANIFEST_TEMPLATE_URL = "/api/manifest-template.csv";
export const batchExportUrl = (id: string) => `/api/verify/batch/${id}/export.csv`;

export async function uploadBatch(zip: File): Promise<BatchState> {
  const form = new FormData();
  form.append("archive", zip);
  return unwrap<BatchState>(
    await fetch("/api/verify/batch", { method: "POST", body: form }),
  );
}

export async function startBatch(id: string): Promise<BatchState> {
  await unwrap(await fetch(`/api/verify/batch/${id}/start`, { method: "POST" }));
  return getBatch(id);
}

export async function getBatch(id: string): Promise<BatchState> {
  return unwrap<BatchState>(await fetch(`/api/verify/batch/${id}`));
}

/** Subscribe to batch progress. Returns an unsubscribe fn. Falls back silently
 *  to nothing if EventSource fails — callers should also poll getBatch(). */
export function streamBatch(
  id: string,
  handlers: { onProgress?: () => void; onDone?: () => void },
): () => void {
  const es = new EventSource(`/api/verify/batch/${id}/events`);
  es.addEventListener("row", () => handlers.onProgress?.());
  es.addEventListener("progress", () => handlers.onProgress?.());
  es.addEventListener("done", () => {
    handlers.onDone?.();
    es.close();
  });
  es.onerror = () => es.close();
  return () => es.close();
}

export async function getBatchRow(
  id: string,
  serial: string,
): Promise<BatchRowState> {
  return unwrap<BatchRowState>(
    await fetch(`/api/verify/batch/${id}/rows/${encodeURIComponent(serial)}`),
  );
}

export async function recordBatchDecision(
  id: string,
  serial: string,
  checkId: string,
  decision: "accept" | "reject",
): Promise<BatchRowState> {
  await unwrap(
    await fetch(
      `/api/verify/batch/${id}/rows/${encodeURIComponent(serial)}/decisions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ check_id: checkId, decision }),
      },
    ),
  );
  return getBatchRow(id, serial);
}

export async function finalizeBatchRow(
  id: string,
  serial: string,
  action: "approve" | "reject" | "request_image",
): Promise<BatchRowState> {
  await unwrap(
    await fetch(
      `/api/verify/batch/${id}/rows/${encodeURIComponent(serial)}/finalize`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      },
    ),
  );
  return getBatchRow(id, serial);
}
