export type Outcome =
  | "PASS"
  | "REVIEW"
  | "FAIL"
  | "UNREADABLE"
  | "NOT_DECLARED";

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Check {
  check_id: string;
  field_label: string;
  outcome: Outcome;
  outcome_label: string;
  declared: string | null;
  observed: string | null;
  detail: string;
  tier: string | null;
  box: Box | null;
  image_index: number | null;
  image_role: string | null;
  evidence: Record<string, unknown>;
}

export interface VerificationResult {
  application_key: string;
  verdict: Outcome;
  summary_line: string;
  elapsed_ms: number;
  stage_ms: Record<string, number>;
  ocr_available: boolean;
  notes: string[];
  checks: Check[];
}

export interface ImageMeta {
  index: number;
  role: string | null;
  width: number;
  height: number;
  url: string;
}

export interface VerifyResponse {
  session_id: string;
  result: VerificationResult;
  images: ImageMeta[];
}

export interface SessionState {
  session_id: string;
  result: VerificationResult;
  images: ImageMeta[];
  decisions: Record<string, "accept" | "reject">;
  unresolved_review_ids: string[];
  can_finalize: boolean;
  finalized: string | null;
}

// ---- batch ---------------------------------------------------------------

export interface PreflightReport {
  fatal: string | null;
  missing_columns: string[];
  row_count: number;
  ok_count: number;
  blocked_count: number;
  rows_missing_images: { line: number; serial: string; missing: string[] }[];
  unreferenced_images: string[];
  duplicate_serials: string[];
  unparseable_values: { line: number; serial: string; field: string; value: string }[];
  row_errors: { line: number; serial: string; errors: string[] }[];
  can_proceed: boolean;
}

export interface BatchRowSummary {
  serial_number: string;
  line: number;
  brand_name: string;
  status: "pending" | "running" | "done" | "error";
  verdict: string;
  blocked_reason: string | null;
  error: string | null;
  needs_attention: number;
  elapsed_ms: number | null;
  unresolved_review_ids: string[];
  can_finalize: boolean;
  finalized: string | null;
}

export interface BatchState {
  batch_id: string;
  state: "ready" | "running" | "complete";
  progress: { done: number; total: number; state: string };
  preflight: PreflightReport;
  rows: BatchRowSummary[];
  exception_serials: string[];
  /** Advisory triage brief. Null is a normal state — no model configured, the
   *  call failed, or there was nothing to triage. The rows are the record. */
  brief: TriageBrief | null;
}

export interface TriageBrief {
  headline: string;
  groups: { label: string; count: number; detail: string }[];
  watch_outs: string[];
  model: string;
  truncated: boolean;
  generated: true;
  advisory: true;
}

export interface DraftedNotice {
  subject: string;
  body: string;
  items: string[];
  model: string;
  generated: true;
  advisory: true;
}

export interface BatchRowState {
  serial_number: string;
  verdict: string;
  status: string;
  blocked_reason: string | null;
  error: string | null;
  result: VerificationResult | null;
  images: ImageMeta[];
  decisions: Record<string, "accept" | "reject">;
  unresolved_review_ids: string[];
  can_finalize: boolean;
  finalized: string | null;
}

/** The shape ReviewScreen needs — both a single-label session and a batch row
 *  can be adapted to this. */
export interface ReviewData {
  result: VerificationResult;
  images: ImageMeta[];
  decisions: Record<string, "accept" | "reject">;
  unresolved_review_ids: string[];
  can_finalize: boolean;
  finalized: string | null;
}

export type Commodity = "wine" | "malt" | "spirits";

export interface DeclaredFields {
  serial_number: string;
  brand_name: string;
  class_type: string;
  commodity: Commodity;
  ttb_id?: string;
  alcohol_content?: string;
  net_contents?: string;
  applicant_name?: string;
  applicant_address?: string;
  origin?: string;
  fanciful_name?: string;
}
