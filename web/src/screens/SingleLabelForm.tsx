import { useId, useState } from "react";
import { verify } from "../api";
import type { Commodity, DeclaredFields } from "../types";

interface Props {
  onVerified: (sessionId: string) => void;
}

const ROLES = ["front", "back", "neck"] as const;

interface Upload {
  file: File;
  role: string;
  preview: string;
}

const FIELD =
  "w-full rounded-lg border border-zinc-300 px-3 py-2.5 text-[17px] " +
  "focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500";
const LABEL = "block text-sm font-medium text-zinc-700 mb-1";

function TextField({
  label,
  value,
  onChange,
  placeholder,
  required,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className={LABEL}>
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      <input
        id={id}
        className={FIELD}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function SingleLabelForm({ onVerified }: Props) {
  const commodityId = useId();
  const [f, setF] = useState<DeclaredFields>({
    serial_number: "",
    brand_name: "",
    class_type: "",
    commodity: "spirits",
  });
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof DeclaredFields) => (v: string) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const next: Upload[] = [];
    Array.from(files).forEach((file, i) => {
      if (!file.type.startsWith("image/")) return;
      next.push({
        file,
        role: ROLES[uploads.length + i] ?? "",
        preview: URL.createObjectURL(file),
      });
    });
    setUploads((prev) => [...prev, ...next]);
  };

  const canSubmit =
    f.serial_number.trim() &&
    f.brand_name.trim() &&
    f.class_type.trim() &&
    uploads.length > 0 &&
    !busy;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const clean = Object.fromEntries(
        Object.entries(f).filter(([, v]) => v !== ""),
      ) as unknown as DeclaredFields;
      const res = await verify(
        clean,
        uploads.map((u) => ({ file: u.file, role: u.role })),
      );
      onVerified(res.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto w-full px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">Check one label</h1>
      <p className="text-zinc-600 mt-1">
        Enter the values from the application, add the label image(s), and press{" "}
        <span className="font-medium">Verify label</span>.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <TextField
          label="Serial number"
          required
          value={f.serial_number}
          onChange={set("serial_number")}
          placeholder="100001"
        />
        <div>
          <label htmlFor={commodityId} className={LABEL}>
            Commodity <span className="text-red-500">*</span>
          </label>
          <select
            id={commodityId}
            className={FIELD}
            value={f.commodity}
            onChange={(e) => set("commodity")(e.target.value as Commodity)}
          >
            <option value="spirits">Distilled spirits</option>
            <option value="wine">Wine</option>
            <option value="malt">Malt beverage</option>
          </select>
        </div>
        <TextField
          label="Brand name"
          required
          className="sm:col-span-2"
          value={f.brand_name}
          onChange={set("brand_name")}
          placeholder="OLD TOM DISTILLERY"
        />
        <TextField
          label="Class / type"
          required
          className="sm:col-span-2"
          value={f.class_type}
          onChange={set("class_type")}
          placeholder="Kentucky Straight Bourbon Whiskey"
        />
        <TextField
          label="Alcohol content"
          value={f.alcohol_content ?? ""}
          onChange={set("alcohol_content")}
          placeholder="45% Alc./Vol."
        />
        <TextField
          label="Net contents"
          value={f.net_contents ?? ""}
          onChange={set("net_contents")}
          placeholder="750 mL"
        />
        <TextField
          label="Producer name"
          value={f.applicant_name ?? ""}
          onChange={set("applicant_name")}
          placeholder="Old Tom Distillery, LLC"
        />
        <TextField
          label="Country of origin"
          value={f.origin ?? ""}
          onChange={set("origin")}
          placeholder="imports only"
        />
      </div>

      <div className="mt-6">
        <span className={LABEL}>
          Label image(s) <span className="text-red-500">*</span>
        </span>
        <label
          className="mt-1 flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-300 bg-white px-6 py-8 text-center cursor-pointer hover:border-sky-400"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            addFiles(e.dataTransfer.files);
          }}
        >
          <span className="text-zinc-700 font-medium">
            Drop images here, or click to choose
          </span>
          <span className="text-sm text-zinc-500 mt-1">
            PNG or JPEG. Front and back if the warning is on the back.
          </span>
          <input
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => addFiles(e.target.files)}
          />
        </label>

        {uploads.length > 0 && (
          <ul className="mt-3 grid gap-3 sm:grid-cols-3">
            {uploads.map((u, i) => (
              <li key={i} className="rounded-lg border border-zinc-200 bg-white p-2">
                <img
                  src={u.preview}
                  alt=""
                  className="h-28 w-full object-contain bg-zinc-50 rounded"
                />
                <div className="mt-2 flex items-center gap-2">
                  <select
                    aria-label={`role for image ${i + 1}`}
                    className="flex-1 rounded border border-zinc-300 px-2 py-1 text-sm"
                    value={u.role}
                    onChange={(e) =>
                      setUploads((prev) =>
                        prev.map((x, j) =>
                          j === i ? { ...x, role: e.target.value } : x,
                        ),
                      )
                    }
                  >
                    <option value="">(no role)</option>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() =>
                      setUploads((prev) => prev.filter((_, j) => j !== i))
                    }
                    className="text-sm text-zinc-500 hover:text-red-600"
                  >
                    remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-red-700">
          {error}
        </p>
      )}

      <button
        disabled={!canSubmit}
        onClick={submit}
        className="mt-6 w-full rounded-xl bg-sky-600 px-6 py-4 text-lg font-semibold text-white shadow-sm transition enabled:hover:bg-sky-700 disabled:opacity-40"
      >
        {busy ? "Reading the label…" : "Verify label"}
      </button>
    </div>
  );
}
