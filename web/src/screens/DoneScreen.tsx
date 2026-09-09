import type { SessionState } from "../types";

interface Props {
  session: SessionState;
  onAgain: () => void;
}

const COPY: Record<string, { title: string; tone: string }> = {
  approve: { title: "Approved", tone: "text-emerald-700" },
  reject: { title: "Rejected", tone: "text-red-700" },
  request_image: { title: "Better image requested", tone: "text-zinc-700" },
};

export function DoneScreen({ session, onAgain }: Props) {
  const c = COPY[session.finalized ?? ""] ?? { title: "Recorded", tone: "" };
  const decided = Object.entries(session.decisions);

  return (
    <div className="max-w-xl mx-auto w-full px-6 py-16 text-center">
      <p className={`text-3xl font-semibold ${c.tone}`}>{c.title}</p>
      <p className="mt-2 text-zinc-600">
        Application {session.result.application_key}. This decision is session-only —
        nothing is stored.
      </p>

      {decided.length > 0 && (
        <ul className="mt-6 text-left inline-block text-sm text-zinc-600">
          {decided.map(([id, d]) => (
            <li key={id}>
              <span className="font-medium">{id}</span>: {d}
            </li>
          ))}
        </ul>
      )}

      <div>
        <button
          onClick={onAgain}
          className="mt-8 rounded-xl bg-sky-600 px-6 py-3 font-semibold text-white hover:bg-sky-700"
        >
          Check another label
        </button>
      </div>
    </div>
  );
}
