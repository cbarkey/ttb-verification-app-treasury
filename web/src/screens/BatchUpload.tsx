import { useState } from "react";
import { MANIFEST_TEMPLATE_URL, uploadBatch } from "../api";
import type { BatchState } from "../types";

interface Props {
  onPreflight: (batch: BatchState) => void;
}

export function BatchUpload({ onPreflight }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      onPreflight(await uploadBatch(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto w-full px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Upload a batch</h1>
      <p className="text-zinc-600 mt-1">
        One ZIP file: <span className="font-mono text-sm">manifest.csv</span> at the
        root, image files alongside. The manifest's{" "}
        <span className="font-mono text-sm">image_files</span> column pairs each row
        to its images (<span className="font-mono text-sm">;</span>-separated).
      </p>

      <a
        href={MANIFEST_TEMPLATE_URL}
        className="mt-4 inline-block text-sky-700 hover:text-sky-900 underline underline-offset-2"
      >
        Download a blank manifest
      </a>

      <label
        className="mt-6 flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-300 bg-white px-6 py-12 text-center cursor-pointer hover:border-sky-400"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files[0];
          if (f) submit(f);
        }}
      >
        <span className="text-zinc-700 font-medium">
          {busy ? "Checking the manifest…" : "Drop the ZIP here, or click to choose"}
        </span>
        <span className="text-sm text-zinc-500 mt-1">
          Up to 400 rows. Nothing is stored after your session.
        </span>
        <input
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) submit(f);
          }}
        />
      </label>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
