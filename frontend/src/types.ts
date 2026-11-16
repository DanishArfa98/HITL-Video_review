// Bentuk data dari API (mengikuti core/schemas.py di backend).

export type Verdict = "pass" | "fail" | "uncertain";
export type Role = "satpam" | "teller" | "cs";
export type TimelineState = "clear" | "uncertain" | "flagged";
export type VideoStatus = "uploaded" | "processing" | "ai_done" | "failed" | "approved" | "rejected";
export type Modality = "audio" | "vision";
export type Severity = "minor" | "major" | "critical";

export interface TranscriptSegment { start: number; end: number; text: string }
export interface FlaggedRange { start: number; end: number; source: string }

export interface ItemResult {
  item_id: string;
  verdict: Verdict;
  confidence: number;
  reason: string;
  moment_sec: number | null;
  evidence: { transcript: TranscriptSegment[]; frames: string[] };
  flagged_ranges: FlaggedRange[];
}

export interface TimelineSegment { start: number; end: number; state: TimelineState; item_ids: string[] }

export interface ResultSummary {
  total: number;
  passed: number;
  failed: number;
  uncertain: number;
  unlocated_item_ids: string[];
  needs_attention: boolean;
}

export interface PrescreenResult {
  video_id: string;
  scenario_id: string;
  role: Role | null;
  template_version: number;
  status: VideoStatus;
  meta: { duration_sec: number; processed_at: string; models: Record<string, string> };
  results: ItemResult[];
  timeline: TimelineSegment[];
  summary: ResultSummary | null;
}

export interface ChecklistItem {
  id: string;
  source: "universal" | "scenario";
  category: string;
  description: string;
  modalities: Modality[];
  severity: Severity;
  enabled: boolean;
}

export interface ChecklistTemplate {
  scenario_id: string;
  scenario_title: string;
  role: Role;
  template_version: number;
  created_by: "ai" | "human";
  items: ChecklistItem[];
}

export interface Override { item_id: string; human_verdict: "pass" | "fail"; note: string; at: string }

export type TemplateEdit =
  | { op: "add"; item: ChecklistItem }
  | { op: "update"; item_id: string; item: ChecklistItem }
  | { op: "remove"; item_id: string };

export interface ReviewSubmission {
  video_id: string;
  reviewer: string;
  overrides: Override[];
  final_decision: "approved" | "rejected";
  decided_at: string;
  template_edits: TemplateEdit[];
}

export interface VideoRow {
  video_id: string;
  scenario_id: string;
  role: Role | null;
  status: VideoStatus;
  summary: ResultSummary | null;
  processed_at: string;
  duration_sec: number;
}

export interface VideoDetail {
  result: PrescreenResult;
  review: (ReviewSubmission & { updated_at?: string }) | null;
  template: ChecklistTemplate | null;
  video_url: string | null;
}

export interface UploadTicket {
  video_id: string;
  key: string;
  upload_url: string;
  headers: Record<string, string>;
  expires_in: number;
}
