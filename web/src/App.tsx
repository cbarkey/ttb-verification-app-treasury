import { useEffect, useState } from "react";
import {
  draftBatchNotice,
  draftNotice,
  finalize,
  finalizeBatchRow,
  getBatchRow,
  getHealth,
  getSession,
  recordBatchDecision,
  recordDecision,
} from "./api";
import { SingleLabelForm } from "./screens/SingleLabelForm";
import { ResultScreen } from "./screens/ResultScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { DoneScreen } from "./screens/DoneScreen";
import { Home } from "./screens/Home";
import { BatchUpload } from "./screens/BatchUpload";
import { BatchPreflight } from "./screens/BatchPreflight";
import { BatchQueue } from "./screens/BatchQueue";
import type { BatchRowState, BatchState, ReviewData, SessionState } from "./types";

function toReviewData(row: BatchRowState): ReviewData {
  return {
    result: row.result ?? {
      application_key: row.serial_number,
      verdict: "UNREADABLE",
      summary_line: row.blocked_reason ?? row.error ?? "No result for this row.",
      elapsed_ms: 0,
      stage_ms: {},
      ocr_available: true,
      notes: [],
      checks: [],
    },
    images: row.images,
    decisions: row.decisions,
    unresolved_review_ids: row.unresolved_review_ids,
    can_finalize: row.can_finalize,
    finalized: row.finalized,
  };
}

type View =
  | { name: "home" }
  | { name: "form" }
  | { name: "result"; session: SessionState }
  | { name: "review"; session: SessionState }
  | { name: "done"; session: SessionState }
  | { name: "batch-upload" }
  | { name: "batch-preflight"; batch: BatchState }
  | { name: "batch-queue"; batchId: string }
  | { name: "batch-review"; batchId: string; row: BatchRowState; queue: string[] };

export function App() {
  const [view, setView] = useState<View>({ name: "home" });

  // Whether a model is configured at all. Drives the "Draft notice" action:
  // showing a button that can only 503 behind Marcus's firewall would be worse
  // than not showing it (N-06 — no model is a normal state, not an error).
  const [aiReady, setAiReady] = useState(false);
  useEffect(() => {
    getHealth()
      .then((h) => setAiReady(h.ai === "available"))
      .catch(() => setAiReady(false));
  }, []);

  const openBatchRow = async (batchId: string, queue: string[], serial: string) => {
    const row = await getBatchRow(batchId, serial);
    setView({ name: "batch-review", batchId, row, queue });
  };

  return (
    <div className="min-h-full flex flex-col">
      <header className="bg-white border-b border-zinc-200">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-baseline gap-3">
          <button
            onClick={() => setView({ name: "home" })}
            className="font-semibold tracking-tight hover:text-sky-700"
          >
            TTB Label Verification
          </button>
          <span className="text-sm text-zinc-500">prototype · not connected to COLA</span>
          {view.name !== "home" && (
            <button
              onClick={() => setView({ name: "home" })}
              className="ml-auto text-sm text-zinc-600 hover:text-zinc-900 underline underline-offset-2"
            >
              Start over
            </button>
          )}
        </div>
      </header>

      <main className="flex-1 flex flex-col">
        {view.name === "home" && (
          <Home
            onSingle={() => setView({ name: "form" })}
            onBatch={() => setView({ name: "batch-upload" })}
          />
        )}

        {view.name === "form" && (
          <SingleLabelForm
            onVerified={async (id) =>
              setView({ name: "result", session: await getSession(id) })
            }
          />
        )}
        {view.name === "result" && (
          <ResultScreen
            session={view.session}
            onReview={() => setView({ name: "review", session: view.session })}
            onFinalized={async (id) =>
              setView({ name: "done", session: await getSession(id) })
            }
          />
        )}
        {view.name === "review" && (
          <ReviewScreen
            data={view.session}
            onDraftNotice={
              aiReady ? () => draftNotice(view.session.session_id) : undefined
            }
            onDecide={(cid, d) => recordDecision(view.session.session_id, cid, d)}
            onFinalize={async (action) =>
              setView({
                name: "done",
                session: await finalize(view.session.session_id, action),
              })
            }
          />
        )}
        {view.name === "done" && (
          <DoneScreen
            session={view.session}
            onAgain={() => setView({ name: "home" })}
          />
        )}

        {view.name === "batch-upload" && (
          <BatchUpload
            onPreflight={(batch) => setView({ name: "batch-preflight", batch })}
          />
        )}
        {view.name === "batch-preflight" && (
          <BatchPreflight
            batch={view.batch}
            onStarted={() =>
              setView({ name: "batch-queue", batchId: view.batch.batch_id })
            }
          />
        )}
        {view.name === "batch-queue" && (
          <BatchQueue
            batchId={view.batchId}
            onReview={(queue, serial) =>
              openBatchRow(view.batchId, queue, serial)
            }
          />
        )}
        {view.name === "batch-review" && (
          <ReviewScreen
            key={view.row.serial_number}
            data={toReviewData(view.row)}
            title={`Serial ${view.row.serial_number}`}
            onDraftNotice={
              aiReady
                ? () => draftBatchNotice(view.batchId, view.row.serial_number)
                : undefined
            }
            nav={{
              index: view.queue.indexOf(view.row.serial_number),
              total: view.queue.length,
              onPrev:
                view.queue.indexOf(view.row.serial_number) > 0
                  ? () =>
                      openBatchRow(
                        view.batchId,
                        view.queue,
                        view.queue[view.queue.indexOf(view.row.serial_number) - 1],
                      )
                  : undefined,
              onNext:
                view.queue.indexOf(view.row.serial_number) < view.queue.length - 1
                  ? () =>
                      openBatchRow(
                        view.batchId,
                        view.queue,
                        view.queue[view.queue.indexOf(view.row.serial_number) + 1],
                      )
                  : undefined,
            }}
            onDecide={async (cid, d) => {
              const r = await recordBatchDecision(
                view.batchId,
                view.row.serial_number,
                cid,
                d,
              );
              setView({ ...view, row: r });
              return toReviewData(r);
            }}
            onFinalize={async (action) => {
              await finalizeBatchRow(view.batchId, view.row.serial_number, action);
              const i = view.queue.indexOf(view.row.serial_number);
              if (i < view.queue.length - 1) {
                openBatchRow(view.batchId, view.queue, view.queue[i + 1]);
              } else {
                setView({ name: "batch-queue", batchId: view.batchId });
              }
            }}
          />
        )}
      </main>
    </div>
  );
}
