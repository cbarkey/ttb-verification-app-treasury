import { useState } from "react";
import { finalize } from "../api";
import { OUTCOME_STYLE } from "../outcome";
import type { SessionState } from "../types";

interface Props {
  session: SessionState;
  onReview: () => void;
  onFinalized: (sessionId: string) => void;
}

export function ResultScreen({ session, onReview, onFinalized }: Props) {
  const { result } = session;
  const [busy, setBusy] = useState(false);

  const passed = result.checks.filter(
    (c) => c.outcome === "PASS" || c.outcome === "NOT_DECLARED",
  ).length;
  const needing = result.checks.filter(
    (c) => c.outcome === "REVIEW" || c.outcome === "FAIL" || c.outcome === "UNREADABLE",
  ).length;

  const kind: "clean" | "attention" | "unreadable" =
    result.verdict === "PASS" || result.verdict === "NOT_DECLARED"
      ? "clean"
      : result.verdict === "UNREADABLE"
        ? "unreadable"
        : "attention";

  const act = async (action: "approve" | "request_image") => {
    setBusy(true);
    onFinalized((await finalize(session.session_id, action)).session_id);
  };

  return (
    <div className="max-w-2xl mx-auto w-full px-6 py-10">
      <div className="rounded-2xl bg-white border border-zinc-200 shadow-sm p-8 text-center">
        <p className="text-2xl font-semibold tracking-tight">{result.summary_line}</p>
        <p className="mt-2 text-zinc-600">
          {passed} of {result.checks.length} checks matched
          {needing > 0 && <> · {needing} need a look</>}
        </p>

        <div className="mt-6">
          {kind === "clean" && (
            <button
              disabled={busy}
              onClick={() => act("approve")}
              className="w-full rounded-xl bg-emerald-600 px-6 py-4 text-lg font-semibold text-white enabled:hover:bg-emerald-700 disabled:opacity-40"
            >
              Approve
            </button>
          )}
          {kind === "attention" && (
            <button
              onClick={onReview}
              className="w-full rounded-xl bg-amber-500 px-6 py-4 text-lg font-semibold text-white hover:bg-amber-600"
            >
              Review {needing} {needing === 1 ? "item" : "items"}
            </button>
          )}
          {kind === "unreadable" && (
            <button
              disabled={busy}
              onClick={() => act("request_image")}
              className="w-full rounded-xl bg-zinc-700 px-6 py-4 text-lg font-semibold text-white enabled:hover:bg-zinc-800 disabled:opacity-40"
            >
              Request a better image
            </button>
          )}
        </div>

        {kind === "clean" && (
          <button
            onClick={onReview}
            className="mt-3 text-sm text-zinc-500 hover:text-zinc-800 underline underline-offset-2"
          >
            See the checks first
          </button>
        )}
      </div>

      <ul className="mt-6 divide-y divide-zinc-100 rounded-xl bg-white border border-zinc-200">
        {result.checks.map((c) => (
          <li key={c.check_id} className="flex items-center gap-3 px-4 py-3">
            <span
              className={`h-2.5 w-2.5 rounded-full shrink-0 ${OUTCOME_STYLE[c.outcome].dot}`}
            />
            <span className="font-medium text-zinc-800">{c.field_label}</span>
            <span
              className={`ml-auto text-sm rounded-full border px-2.5 py-0.5 ${OUTCOME_STYLE[c.outcome].chip}`}
            >
              {c.outcome_label}
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-4 text-center text-sm text-zinc-500">
        Read in {result.elapsed_ms} ms
        {!result.ocr_available && " · OCR unavailable — ran in degraded mode"}
      </p>
    </div>
  );
}
