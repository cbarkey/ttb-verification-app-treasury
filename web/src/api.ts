import type {
  BatchRowState,
  BatchState,
  DeclaredFields,
  DraftedNotice,
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

export interface Health {
  status: string;
  ocr: string;
  ocr_engine: string;
  active_sessions: number;
  /** "available" only when a model is configured. Behind a firewall or with no
   *  key this is "unavailable", which is a normal state, not an error (N-06). */
  ai: "available" | "unavailable";
  ai_model: string | null;
  ai_unavailable_reason: string | null;
}

export async function getHealth(): Promise<Health> {
  return unwrap<Health>(await fetch("/api/health"));
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

/** Draft rejection language for a label (DESIGN.md 2.9, use C).
 *  Behind an explicit action, so it costs nothing unless an agent asks. */
export async function draftNotice(id: string): Promise<DraftedNotice> {
  return unwrap<DraftedNotice>(
    await fetch(`/api/sessions/${id}/draft-notice`, { method: "POST" }),
  );
}

export async function draftBatchNotice(
  id: string,
  serial: string,
): Promise<DraftedNotice> {
  return unwrap<DraftedNotice>(
    await fetch(
      `/api/verify/batch/${id}/rows/${encodeURIComponent(serial)}/draft-notice`,
      { method: "POST" },
    ),
  );
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
