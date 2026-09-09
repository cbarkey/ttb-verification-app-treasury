import type {
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
