/**
 * A drafted rejection notice (CLAUDE.md 2.9, use C).
 *
 * The agent owns this text. That is a UI decision as much as a policy one, so
 * the panel is built to make it obvious: the draft lands in an editable
 * textarea, it is labelled generated, and the only action is Copy. There is no
 * Send button, because sending is not this prototype's job and a button that
 * looked like it sent would misrepresent what happened.
 *
 * `items` comes back separately from `body` so a line can be dropped without
 * rewriting the paragraph it was in.
 */
import { useState } from "react";
import type { DraftedNotice } from "../types";
import { GeneratedBanner } from "./AiLabel";

export function NoticeDrawer({
  notice,
  onClose,
}: {
  notice: DraftedNotice;
  onClose: () => void;
}) {
  const [body, setBody] = useState(notice.body);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(`${notice.subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-zinc-900/30">
      <div className="w-full max-w-xl bg-white shadow-xl flex flex-col">
        <div className="flex items-center gap-3 border-b border-zinc-200 px-5 py-3">
          <h2 className="font-semibold text-zinc-800">Draft notice</h2>
          <button
            onClick={onClose}
            className="ml-auto rounded px-2 py-1 text-zinc-500 hover:bg-zinc-100"
          >
            Close
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <GeneratedBanner model={notice.model}>
            Written from the findings above. Every value in it came from the
            rules engine — check it, edit it, and send it yourself.
          </GeneratedBanner>

          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Subject
            </label>
            <p className="mt-1 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm">
              {notice.subject}
            </p>
          </div>

          <div>
            <label
              htmlFor="notice-body"
              className="text-xs font-medium uppercase tracking-wide text-zinc-500"
            >
              Body
            </label>
            <textarea
              id="notice-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={16}
              className="mt-1 w-full rounded-lg border border-zinc-300 p-3 text-sm leading-relaxed focus:border-sky-500 focus:outline-none"
            />
          </div>

          {notice.items.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                Points raised
              </p>
              <ul className="mt-1 list-disc pl-5 text-sm text-zinc-700 space-y-1">
                {notice.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="border-t border-zinc-200 px-5 py-3 flex justify-end gap-3">
          <button
            onClick={copy}
            className="rounded-lg bg-zinc-800 px-5 py-2.5 font-semibold text-white hover:bg-zinc-900"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
    </div>
  );
}
