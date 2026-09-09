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
