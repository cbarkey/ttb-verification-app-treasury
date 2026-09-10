import { useState } from "react";
import { finalize } from "../api";
import { VisionBadge, isFromModel } from "../components/AiLabel";
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

  // 2.9: the result screen says when a model was consulted at all, before the
  // agent opens the review. Being told after the fact is not attribution.
  const modelRead = result.checks.filter(isFromModel);

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

        {kind !== "attention" && (
          <button
            onClick={onReview}
            className="mt-3 text-sm text-zinc-500 hover:text-zinc-800 underline underline-offset-2"
          >
            {/* An unreadable label used to be a dead end. Now that a vision
                model can offer readings for exactly those fields, the agent
                needs a way in to confirm them (2.9 use A). */}
            {modelRead.length > 0
              ? "See what the model read"
              : "See the checks first"}
          </button>
        )}
      </div>

      {modelRead.length > 0 && (
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-sm text-amber-950">
          <p>
            OCR couldn&rsquo;t read{" "}
            {modelRead.length === 1
              ? "one field"
              : `${modelRead.length} fields`}{" "}
            on this label, so a vision model was asked what it says:{" "}
            <span className="font-medium">
              {modelRead.map((c) => c.field_label).join(", ")}
            </span>
            . Those readings need your confirmation — a model reading is never
            approved automatically.
          </p>
        </div>
      )}

      <ul className="mt-6 divide-y divide-zinc-100 rounded-xl bg-white border border-zinc-200">
        {result.checks.map((c) => (
          <li key={c.check_id} className="flex items-center gap-3 px-4 py-3">
            <span
              className={`h-2.5 w-2.5 rounded-full shrink-0 ${OUTCOME_STYLE[c.outcome].dot}`}
            />
            <span className="font-medium text-zinc-800">{c.field_label}</span>
            {isFromModel(c) && <VisionBadge check={c} compact />}
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
