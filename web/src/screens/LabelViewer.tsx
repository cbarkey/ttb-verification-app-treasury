import { useLayoutEffect, useRef, useState } from "react";
import { OUTCOME_STYLE } from "../outcome";
import type { Check, ImageMeta } from "../types";

interface Props {
  image: ImageMeta;
  checks: Check[]; // only checks whose box is on THIS image
  activeId: string | null;
  onPick: (checkId: string) => void;
}

const pct = (n: number, of: number) => `${(n / of) * 100}%`;

export function LabelViewer({ image, checks, activeId, onPick }: Props) {
  const active = checks.find((c) => c.check_id === activeId) ?? null;

  return (
    <div className="space-y-3">
      <div className="relative overflow-hidden rounded-lg border border-zinc-200 bg-white">
        <img src={image.url} alt={image.role ?? "label"} className="block w-full" />

        {/* dim everything except the active region */}
        {active?.box && (
          <div
            className="pointer-events-none absolute"
            style={{
              left: pct(active.box.left, image.width),
              top: pct(active.box.top, image.height),
              width: pct(active.box.width, image.width),
              height: pct(active.box.height, image.height),
              boxShadow: "0 0 0 9999px rgba(24,24,27,0.55)",
            }}
          />
        )}

        {/* clickable outline for every located check on this image */}
        {checks.map((c) =>
          c.box ? (
            <button
              key={c.check_id}
              onClick={() => onPick(c.check_id)}
              title={`${c.field_label} — ${c.outcome_label}`}
              className="absolute transition"
              style={{
                left: pct(c.box.left, image.width),
                top: pct(c.box.top, image.height),
                width: pct(c.box.width, image.width),
                height: pct(c.box.height, image.height),
                border: `${c.check_id === activeId ? 3 : 2}px solid ${OUTCOME_STYLE[c.outcome].stroke}`,
                borderRadius: 3,
                background:
                  c.check_id === activeId ? "transparent" : "rgba(255,255,255,0.01)",
              }}
            />
          ) : null,
        )}
      </div>

      <CropView image={image} check={active} />
    </div>
  );
}

function CropView({ image, check }: { image: ImageMeta; check: Check | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 176 });

  useLayoutEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!check?.box) {
    return (
      <div
        ref={ref}
        className="h-44 rounded-lg border border-dashed border-zinc-300 bg-zinc-50 grid place-items-center text-sm text-zinc-400"
      >
        pick a check to zoom in
      </div>
    );
  }

  const b = check.box;
  const zByW = (size.w * 0.86) / b.width;
  const zByH = (size.h * 0.86) / b.height;
  // Fit the region to the crop box: zoom out for a big block, in for a small one.
  const z = Math.min(Math.max(Math.min(zByW, zByH), 0.1), 9);
  const left = size.w / 2 - (b.left + b.width / 2) * z;
  const top = size.h / 2 - (b.top + b.height / 2) * z;

  return (
    <div
      ref={ref}
      className="relative h-44 overflow-hidden rounded-lg border border-zinc-200 bg-white"
    >
      <img
        src={image.url}
        alt=""
        className="absolute max-w-none select-none"
        style={{ width: image.width * z, left, top }}
      />
      <div
        className="pointer-events-none absolute"
        style={{
          left: size.w / 2 - (b.width * z) / 2,
          top: size.h / 2 - (b.height * z) / 2,
          width: b.width * z,
          height: b.height * z,
          border: `2px solid ${OUTCOME_STYLE[check.outcome].stroke}`,
          borderRadius: 3,
        }}
      />
    </div>
  );
}
