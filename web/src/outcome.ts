import type { Outcome } from "./types";

/** Colour + copy per outcome. Kept in one place so the checks list, the image
 *  overlay, and the verdict banner never drift apart. */
export const OUTCOME_STYLE: Record<
  Outcome,
  { dot: string; ring: string; chip: string; stroke: string }
> = {
  PASS: {
    dot: "bg-emerald-500",
    ring: "ring-emerald-500",
    chip: "bg-emerald-50 text-emerald-700 border-emerald-200",
    stroke: "#059669",
  },
  REVIEW: {
    dot: "bg-amber-500",
    ring: "ring-amber-500",
    chip: "bg-amber-50 text-amber-800 border-amber-200",
    stroke: "#d97706",
  },
  FAIL: {
    dot: "bg-red-600",
    ring: "ring-red-600",
    chip: "bg-red-50 text-red-700 border-red-200",
    stroke: "#dc2626",
  },
  UNREADABLE: {
    dot: "bg-zinc-500",
    ring: "ring-zinc-500",
    chip: "bg-zinc-100 text-zinc-700 border-zinc-300",
    stroke: "#71717a",
  },
  NOT_DECLARED: {
    dot: "bg-zinc-300",
    ring: "ring-zinc-300",
    chip: "bg-zinc-50 text-zinc-500 border-zinc-200",
    stroke: "#a1a1aa",
  },
};

export const NEEDS_ATTENTION: Outcome[] = ["FAIL", "REVIEW", "UNREADABLE"];
