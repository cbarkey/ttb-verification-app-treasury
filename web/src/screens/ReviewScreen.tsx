import { useMemo, useState } from "react";
import { finalize, recordDecision } from "../api";
import { NEEDS_ATTENTION, OUTCOME_STYLE } from "../outcome";
import type { Check, SessionState } from "../types";
import { LabelViewer } from "./LabelViewer";

interface Props {
  session: SessionState;
  onSessionChange: (s: SessionState) => void;
  onFinalized: (sessionId: string) => void;
}

function decisionLabels(c: Check): { accept: string; reject: string } {
  if (c.check_id === "warn_bold") return { accept: "Bold enough", reject: "Not bold" };
  if (c.tier === "fuzzy") return { accept: "Same product", reject: "Not a match" };
  return { accept: "Accept", reject: "Reject" };
}

export function ReviewScreen({ session, onSessionChange, onFinalized }: Props) {
  const { result, images } = session;

  const attention = useMemo(
    () => result.checks.filter((c) => NEEDS_ATTENTION.includes(c.outcome)),
    [result.checks],
  );
  const passed = result.checks.filter((c) => !NEEDS_ATTENTION.includes(c.outcome));

  const [activeId, setActiveId] = useState<string | null>(
    attention.find((c) => c.box)?.check_id ?? attention[0]?.check_id ?? null,
  );
  const active = result.checks.find((c) => c.check_id === activeId) ?? null;
  const [tab, setTab] = useState<number>(active?.image_index ?? 0);
  const [showPassed, setShowPassed] = useState(false);
  const [busy, setBusy] = useState(false);

  const pick = (id: string) => {
    setActiveId(id);
    const c = result.checks.find((x) => x.check_id === id);
    if (c?.image_index != null) setTab(c.image_index);
  };

  const decide = async (checkId: string, decision: "accept" | "reject") => {
    setBusy(true);
    try {
      const next = await recordDecision(session.session_id, checkId, decision);
      onSessionChange(next);
      const stillOpen = next.unresolved_review_ids;
      if (stillOpen.length) pick(stillOpen[0]);
    } finally {
      setBusy(false);
    }
  };

  const doFinalize = async (action: "approve" | "reject" | "request_image") => {
    setBusy(true);
    onFinalized((await finalize(session.session_id, action)).session_id);
  };

  const checksOnTab = result.checks.filter((c) => c.box && c.image_index === tab);

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex-1 grid lg:grid-cols-[minmax(360px,440px)_1fr] min-h-0">
        {/* LEFT — checks */}
        <div className="border-r border-zinc-200 bg-white overflow-y-auto">
          <div className="px-5 py-4 border-b border-zinc-100">
            <p className="text-lg font-semibold">{result.summary_line}</p>
            <p className="text-sm text-zinc-500">
              {session.unresolved_review_ids.length > 0
                ? `${session.unresolved_review_ids.length} still to resolve`
                : "all review items resolved"}
            </p>
          </div>

          <ul>
            {attention.map((c) => (
              <CheckRow
                key={c.check_id}
                check={c}
                active={c.check_id === activeId}
                decision={session.decisions[c.check_id]}
                busy={busy}
                onSelect={() => pick(c.check_id)}
                onDecide={decide}
              />
            ))}
          </ul>

          {passed.length > 0 && (
            <div className="border-t border-zinc-100">
              <button
                onClick={() => setShowPassed((v) => !v)}
                className="w-full px-5 py-3 text-left text-sm font-medium text-zinc-500 hover:bg-zinc-50"
              >
                {showPassed ? "▾" : "▸"} {passed.length} passed
              </button>
              {showPassed && (
                <ul className="pb-2">
                  {passed.map((c) => (
                    <CheckRow
                      key={c.check_id}
                      check={c}
                      active={c.check_id === activeId}
                      decision={undefined}
                      busy={busy}
                      onSelect={() => pick(c.check_id)}
                      onDecide={decide}
                    />
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* RIGHT — label image */}
        <div className="bg-zinc-100 overflow-y-auto p-5">
          {images.length > 1 && (
            <div className="mb-3 flex gap-1">
              {images.map((im) => (
                <button
                  key={im.index}
                  onClick={() => setTab(im.index)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize ${
                    im.index === tab
                      ? "bg-white shadow-sm text-zinc-900"
                      : "text-zinc-500 hover:text-zinc-800"
                  }`}
                >
                  {im.role ?? `image ${im.index + 1}`}
                </button>
              ))}
            </div>
          )}
          {images[tab] && (
            <div className="max-w-lg mx-auto">
              <LabelViewer
                image={images[tab]}
                checks={checksOnTab}
                activeId={activeId}
                onPick={pick}
              />
            </div>
          )}
        </div>
      </div>

      {/* FOOTER — the one decision that matters */}
      <div className="border-t border-zinc-200 bg-white px-5 py-3 flex flex-wrap gap-3 justify-end items-center">
        {!session.can_finalize && (
          <span className="mr-auto text-sm text-amber-700">
            Resolve the review items above to enable Approve.
          </span>
        )}
        <button
          disabled={busy}
          onClick={() => doFinalize("request_image")}
          className="rounded-lg px-4 py-2.5 font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-40"
        >
          Request better image
        </button>
        <button
          disabled={busy}
          onClick={() => doFinalize("reject")}
          className="rounded-lg px-5 py-2.5 font-semibold text-red-700 border border-red-200 hover:bg-red-50 disabled:opacity-40"
        >
          Reject
        </button>
        <button
          disabled={busy || !session.can_finalize}
          onClick={() => doFinalize("approve")}
          className="rounded-lg bg-emerald-600 px-6 py-2.5 font-semibold text-white hover:bg-emerald-700 disabled:opacity-40"
        >
          Approve
        </button>
      </div>
    </div>
  );
}

function CheckRow({
  check,
  active,
  decision,
  busy,
  onSelect,
  onDecide,
}: {
  check: Check;
  active: boolean;
  decision: "accept" | "reject" | undefined;
  busy: boolean;
  onSelect: () => void;
  onDecide: (id: string, d: "accept" | "reject") => void;
}) {
  const s = OUTCOME_STYLE[check.outcome];
  const labels = decisionLabels(check);
  const diff = (check.evidence?.diff as DiffEntry[] | undefined) ?? [];

  return (
    <li
      className={`border-b border-zinc-100 ${active ? "bg-sky-50/60" : ""}`}
    >
      <button
        onClick={onSelect}
        className={`w-full text-left px-5 py-3 ${active ? "ring-2 ring-inset ring-sky-400" : ""}`}
      >
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${s.dot}`} />
          <span className="font-semibold text-zinc-800">{check.field_label}</span>
          <span
            className={`ml-auto text-xs rounded-full border px-2 py-0.5 ${s.chip}`}
          >
            {check.outcome_label}
          </span>
        </div>

        {(check.declared || check.observed) && (
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
            {check.declared != null && (
              <>
                <dt className="text-zinc-400">Application</dt>
                <dd className="text-zinc-700">{check.declared}</dd>
              </>
            )}
            {check.observed != null && (
              <>
                <dt className="text-zinc-400">Label</dt>
                <dd className="text-zinc-700">{check.observed}</dd>
              </>
            )}
          </dl>
        )}

        {check.detail && (
          <p className="mt-1 text-sm text-zinc-500">{check.detail}</p>
        )}

        {check.outcome === "FAIL" && diff.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1 text-xs">
            {diff
              .filter((d) => d.kind !== "ocr_noise")
              .map((d, i) => (
                <span
                  key={i}
                  className="rounded bg-red-50 border border-red-200 px-1.5 py-0.5 text-red-700"
                >
                  {d.kind === "missing"
                    ? `missing “${d.expected}”`
                    : d.kind === "extra"
                      ? `extra “${d.got}”`
                      : `“${d.expected}” → “${d.got}”`}
                </span>
              ))}
          </div>
        )}
      </button>

      {check.outcome === "REVIEW" && (
        <div className="px-5 pb-3 flex gap-2">
          <button
            disabled={busy}
            onClick={() => onDecide(check.check_id, "accept")}
            className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold border disabled:opacity-40 ${
              decision === "accept"
                ? "bg-emerald-600 text-white border-emerald-600"
                : "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
            }`}
          >
            {labels.accept}
          </button>
          <button
            disabled={busy}
            onClick={() => onDecide(check.check_id, "reject")}
            className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold border disabled:opacity-40 ${
              decision === "reject"
                ? "bg-red-600 text-white border-red-600"
                : "border-red-300 text-red-700 hover:bg-red-50"
            }`}
          >
            {labels.reject}
          </button>
        </div>
      )}
    </li>
  );
}

interface DiffEntry {
  pos: number;
  expected: string | null;
  got: string | null;
  kind: "substituted" | "missing" | "extra" | "ocr_noise";
}
