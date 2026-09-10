/**
 * Attribution for anything a model touched (CLAUDE.md 2.9).
 *
 * The rule the UI has to make good on: an agent must always be able to tell
 * which findings came from a model and which came from deterministic code. So
 * model-sourced content is marked wherever it appears, with the model id, and
 * the mark says what the agent is expected to do about it ("confirm") rather
 * than just naming a technology.
 *
 * Deliberately not a subtle icon. The whole safety argument is that a model
 * reading is a question, not an answer, and that reads better as a visible
 * amber tag than as a tooltip.
 */
import type { Check } from "../types";

/** True when this check's *reading* came from the vision model rather than OCR. */
export function isFromModel(check: Check): boolean {
  return check.evidence?.source === "vision_model";
}

export function modelIdOf(check: Check): string | null {
  const model = check.evidence?.model;
  return typeof model === "string" && model ? model : null;
}

export function VisionBadge({
  check,
  compact = false,
}: {
  check: Check;
  /** Drops the model id. For dense list rows, where the tag is a marker and the
   *  detail belongs on the review row that can afford the width. */
  compact?: boolean;
}) {
  if (!isFromModel(check)) return null;
  const model = compact ? null : modelIdOf(check);
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800"
      title={
        "OCR could not read this field, so a vision model was asked what the " +
        "label says. A model reading is never approved automatically — it is " +
        "always routed to you to confirm."
      }
    >
      <span aria-hidden>👁</span>
      read by vision model — confirm
      {model && <span className="font-normal text-amber-700/80">· {model}</span>}
    </span>
  );
}

/** Header for generated prose (the batch brief, a drafted notice). */
export function GeneratedBanner({
  model,
  children,
}: {
  model?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-amber-800">
        <span aria-hidden>✦</span>
        AI-generated summary — advisory only
        {model && (
          <span className="font-normal normal-case tracking-normal text-amber-700/80">
            · {model}
          </span>
        )}
      </div>
      <div className="mt-2 text-sm text-amber-950">{children}</div>
    </div>
  );
}
