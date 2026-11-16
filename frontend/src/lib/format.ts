import type { Role, VideoStatus } from "../types";

export const ROLE_LABEL: Record<Role, string> = {
  satpam: "Satpam",
  teller: "Teller",
  cs: "Customer Service",
};

export const STATUS_LABEL: Record<VideoStatus, string> = {
  uploaded: "Diunggah",
  processing: "Diproses",
  ai_done: "Menunggu review",
  failed: "Gagal diproses",
  approved: "Disetujui",
  rejected: "Ditolak",
};

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("id-ID", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** "satpam-melayani-nasabah" -> "Satpam melayani nasabah" */
export function humanizeSlug(slug: string): string {
  const text = slug.replace(/-/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
