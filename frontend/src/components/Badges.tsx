import { STATUS_LABEL } from "../lib/format";
import type { Verdict, VideoStatus } from "../types";

export function StatusBadge({ status }: { status: VideoStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

const VERDICT_LABEL: Record<Verdict, string> = { pass: "Lolos", fail: "Gagal", uncertain: "Ragu" };

export function VerdictBadge({ verdict, prefix }: { verdict: Verdict; prefix?: string }) {
  return (
    <span className={`badge badge-${verdict}`}>
      {prefix ? `${prefix} ` : ""}
      {VERDICT_LABEL[verdict]}
    </span>
  );
}
