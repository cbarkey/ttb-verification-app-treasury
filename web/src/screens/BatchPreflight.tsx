import { useState } from "react";
import { startBatch } from "../api";
import type { BatchState } from "../types";

interface Props {
  batch: BatchState;
  onStarted: () => void;
}

function Issue({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <p className="font-medium text-amber-900">{title}</p>
      <div className="mt-1 text-sm text-amber-800">{children}</div>
    </div>
  );
}

export function BatchPreflight({ batch, onStarted }: Props) {
  const pf = batch.preflight;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await startBatch(batch.batch_id);
      onStarted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto w-full px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Check the batch</h1>
      <p className="text-zinc-600 mt-1">
        Nothing is verified yet — here's what the manifest and ZIP look like.
      </p>

      <div className="mt-6 flex gap-4">
        <div className="flex-1 rounded-xl border border-zinc-200 bg-white px-5 py-4 text-center">
          <p className="text-3xl font-semibold text-emerald-700">{pf.ok_count}</p>
          <p className="text-sm text-zinc-500">rows ready to verify</p>
        </div>
        <div className="flex-1 rounded-xl border border-zinc-200 bg-white px-5 py-4 text-center">
          <p
            className={`text-3xl font-semibold ${
              pf.blocked_count ? "text-red-600" : "text-zinc-400"
            }`}
          >
            {pf.blocked_count}
          </p>
          <p className="text-sm text-zinc-500">rows blocked</p>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {pf.missing_columns.length > 0 && (
          <Issue title="The manifest is missing required columns">
            {pf.missing_columns.join(", ")} — nothing can be processed until these
            are added.
          </Issue>
        )}
        {pf.rows_missing_images.length > 0 && (
          <Issue
            title={`${pf.rows_missing_images.length} row(s) point at images not in the ZIP`}
          >
            {pf.rows_missing_images.slice(0, 8).map((r) => (
              <div key={r.serial}>
                row {r.line} ({r.serial}): {r.missing.join(", ")}
              </div>
            ))}
          </Issue>
        )}
        {pf.duplicate_serials.length > 0 && (
          <Issue title="Duplicate serial numbers">
            {pf.duplicate_serials.join(", ")}
          </Issue>
        )}
        {pf.unparseable_values.length > 0 && (
          <Issue title={`${pf.unparseable_values.length} declared value(s) won't parse`}>
            {pf.unparseable_values.slice(0, 8).map((u, i) => (
              <div key={i}>
                row {u.line} ({u.serial}): {u.field} = “{u.value}”
              </div>
            ))}
          </Issue>
        )}
        {pf.unreferenced_images.length > 0 && (
          <Issue title={`${pf.unreferenced_images.length} image(s) in the ZIP with no manifest row`}>
            {pf.unreferenced_images.slice(0, 10).join(", ")}
          </Issue>
        )}
        {pf.row_errors.length > 0 && (
          <Issue title={`${pf.row_errors.length} row(s) have field problems`}>
            {pf.row_errors.slice(0, 8).map((r) => (
              <div key={r.serial || r.line}>
                row {r.line}: {r.errors.join("; ")}
              </div>
            ))}
          </Issue>
        )}
      </div>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-red-700">
          {error}
        </p>
      )}

      <button
        disabled={busy || !pf.can_proceed}
        onClick={start}
        className="mt-6 w-full rounded-xl bg-sky-600 px-6 py-4 text-lg font-semibold text-white enabled:hover:bg-sky-700 disabled:opacity-40"
      >
        {pf.can_proceed
          ? busy
            ? "Starting…"
            : `Verify ${pf.ok_count} row${pf.ok_count === 1 ? "" : "s"}`
          : "Fix the manifest and re-upload"}
      </button>
      {pf.can_proceed && pf.blocked_count > 0 && (
        <p className="mt-2 text-center text-sm text-zinc-500">
          The {pf.blocked_count} blocked row(s) will be skipped.
        </p>
      )}
    </div>
  );
}
