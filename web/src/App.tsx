import { useState } from "react";
import { getSession } from "./api";
import { SingleLabelForm } from "./screens/SingleLabelForm";
import { ResultScreen } from "./screens/ResultScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { DoneScreen } from "./screens/DoneScreen";
import type { SessionState } from "./types";

type View =
  | { name: "form" }
  | { name: "result"; session: SessionState }
  | { name: "review"; session: SessionState }
  | { name: "done"; session: SessionState };

export function App() {
  const [view, setView] = useState<View>({ name: "form" });

  const refresh = async (id: string, name: "result" | "review" | "done") => {
    const session = await getSession(id);
    setView(
      name === "result"
        ? { name, session }
        : name === "review"
          ? { name, session }
          : { name, session },
    );
  };

  return (
    <div className="min-h-full flex flex-col">
      <header className="bg-white border-b border-zinc-200">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-baseline gap-3">
          <span className="font-semibold tracking-tight">TTB Label Verification</span>
          <span className="text-sm text-zinc-500">prototype · not connected to COLA</span>
          {view.name !== "form" && (
            <button
              onClick={() => setView({ name: "form" })}
              className="ml-auto text-sm text-zinc-600 hover:text-zinc-900 underline underline-offset-2"
            >
              Start over
            </button>
          )}
        </div>
      </header>

      <main className="flex-1 flex flex-col">
        {view.name === "form" && (
          <SingleLabelForm
            onVerified={(id) => refresh(id, "result")}
          />
        )}
        {view.name === "result" && (
          <ResultScreen
            session={view.session}
            onReview={() => setView({ name: "review", session: view.session })}
            onFinalized={(id) => refresh(id, "done")}
          />
        )}
        {view.name === "review" && (
          <ReviewScreen
            session={view.session}
            onSessionChange={(s) => setView({ name: "review", session: s })}
            onFinalized={(id) => refresh(id, "done")}
          />
        )}
        {view.name === "done" && (
          <DoneScreen
            session={view.session}
            onAgain={() => setView({ name: "form" })}
          />
        )}
      </main>
    </div>
  );
}
