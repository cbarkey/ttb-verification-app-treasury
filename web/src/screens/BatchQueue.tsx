import { useEffect, useRef, useState } from "react";
import { batchExportUrl, getBatch, streamBatch } from "../api";
import { GeneratedBanner } from "../components/AiLabel";
import { OUTCOME_STYLE } from "../outcome";
import type { BatchState } from "../types";

interface Props {
  batchId: string;
  onReview: (queue: string[], serial: string) => void;
}

const VERDICT_STYLE: Record<string, string> = {
  FAIL: OUTCOME_STYLE.FAIL.chip,
  REVIEW: OUTCOME_STYLE.REVIEW.chip,
  UNREADABLE: OUTCOME_STYLE.UNREADABLE.chip,
  ERROR: OUTCOME_STYLE.FAIL.chip,
  BLOCKED: OUTCOME_STYLE.UNREADABLE.chip,
  PASS: OUTCOME_STYLE.PASS.chip,
  PENDING: "bg-zinc-100 text-zinc-500 border-zinc-200",
};

export function BatchQueue({ batchId, onReview }: Props) {
  const [batch, setBatch] = useState<BatchState | null>(null);
  const polling = useRef(false);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        const b = await getBatch(batchId);
        if (alive) setBatch(b);
      } finally {
        polling.current = false;
      }
    };
    refresh();
    const stop = streamBatch(batchId, { onProgress: refresh, onDone: refresh });
    const poll = setInterval(refresh, 1500); // fallback if SSE drops
    return () => {
      alive = false;
      stop();
      clearInterval(poll);
    };
  }, [batchId]);

  if (!batch) {
    return <div className="px-6 py-10 text-zinc-500">Loading…</div>;
  }

  const { progress } = batch;
  const done = batch.state === "complete";
  const queue = batch.exception_serials;

  return (
    <div className="max-w-5xl mx-auto w-full px-6 py-8">
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Batch results</h1>
        <a
          href={batchExportUrl(batchId)}
          className="ml-auto text-sm text-sky-700 hover:text-sky-900 underline underline-offset-2"
        >
          Export decisions (CSV)
        </a>
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between text-sm text-zinc-600">
          <span>
            {done
              ? `All ${progress.total} verified`
              : `Verifying… ${progress.done} of ${progress.total}`}
          </span>
          {queue.length > 0 && (
            <button
              onClick={() => onReview(queue, queue[0])}
              className="rounded-lg bg-amber-500 px-4 py-1.5 font-semibold text-white hover:bg-amber-600"
            >
              Review {queue.length} exception{queue.length === 1 ? "" : "s"}
            </button>
          )}
        </div>
        <div className="mt-1 h-2 rounded-full bg-zinc-200 overflow-hidden">
          <div
            className="h-full bg-sky-500 transition-all"
            style={{
              width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%`,
            }}
          />
        </div>
      </div>

      {batch.brief && <TriageBrief brief={batch.brief} />}

      <table className="mt-5 w-full text-sm">
        <thead>
          <tr className="text-left text-zinc-400 border-b border-zinc-200">
            <th className="py-2 font-medium">Serial</th>
            <th className="py-2 font-medium">Brand</th>
            <th className="py-2 font-medium">Result</th>
            <th className="py-2 font-medium">Needs attention</th>
            <th className="py-2 font-medium">ms</th>
            <th className="py-2"></th>
          </tr>
        </thead>
        <tbody>
          {batch.rows.map((r) => {
            const actionable = ["FAIL", "REVIEW", "UNREADABLE", "ERROR"].includes(
              r.verdict,
            );
            return (
              <tr
                key={r.serial_number}
                className="border-b border-zinc-100 hover:bg-zinc-50"
              >
                <td className="py-2 font-medium text-zinc-800">{r.serial_number}</td>
                <td className="py-2 text-zinc-600">{r.brand_name}</td>
                <td className="py-2">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.PENDING
                    }`}
                  >
                    {r.status === "running" || r.status === "pending"
                      ? "…"
                      : r.finalized
                        ? `${r.verdict} · ${r.finalized}`
                        : r.verdict}
                  </span>
                  {r.blocked_reason && (
                    <span className="ml-2 text-xs text-zinc-400">
                      {r.blocked_reason}
                    </span>
                  )}
                </td>
                <td className="py-2 text-zinc-600">
                  {r.needs_attention || (r.status === "done" ? "—" : "")}
                </td>
                <td className="py-2 text-zinc-400">{r.elapsed_ms ?? ""}</td>
                <td className="py-2 text-right">
                  {actionable && (
                    <button
                      onClick={() => onReview(queue, r.serial_number)}
                      className="rounded-md border border-zinc-300 px-3 py-1 font-medium text-zinc-700 hover:bg-white"
                    >
                      Review
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The triage brief (CLAUDE.md 2.9, use B).
 *
 * Prose *above* the table, never inside it. The table is the record and the
 * brief is one supervisor's-eye read of it — so it is visually separated,
 * labelled generated and advisory, and carries the model id. Nothing here is
 * clickable into a decision.
 */
function TriageBrief({ brief }: { brief: NonNullable<BatchState["brief"]> }) {
  return (
    <div className="mt-5">
      <GeneratedBanner model={brief.model}>
        <p className="font-medium">{brief.headline}</p>

        {brief.groups.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {brief.groups.map((g, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-0.5 shrink-0 rounded bg-amber-200/70 px-1.5 text-xs font-semibold tabular-nums">
                  {g.count || "—"}
                </span>
                <span>
                  <span className="font-medium">{g.label}</span> — {g.detail}
                </span>
              </li>
            ))}
          </ul>
        )}

        {brief.watch_outs.length > 0 && (
          <ul className="mt-2 list-disc pl-5 space-y-0.5 text-amber-900/90">
            {brief.watch_outs.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}

        {brief.truncated && (
          <p className="mt-2 text-xs text-amber-800/80">
            Summarised from the first exceptions only — the table below is
            complete.
          </p>
        )}
      </GeneratedBanner>
    </div>
  );
}
