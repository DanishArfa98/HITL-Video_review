import type {
  ChecklistItem,
  ItemResult,
  Override,
  TemplateEdit,
  Verdict,
} from "../types";

/** Pass dengan confidence di bawah ini tetap ditampilkan sebagai "perlu dilirik". */
export const LOW_CONFIDENCE = 0.8;

/** Keputusan reviewer per item. Keberadaan entri berarti item sudah ditinjau.
 *  human = null berarti "setuju dengan AI". */
export interface Decision {
  human: "pass" | "fail" | null;
  note: string;
}
export type Decisions = Record<string, Decision>;

export function needsCheck(r: ItemResult): boolean {
  return r.verdict !== "pass" || r.confidence < LOW_CONFIDENCE;
}

const ORDER: Record<Verdict, number> = { fail: 0, uncertain: 1, pass: 2 };

/** Item yang perlu dicek (gagal, ragu, lolos tapi kurang yakin) di atas, sisanya lolos. */
export function partitionItems(results: ItemResult[]): { check: ItemResult[]; ok: ItemResult[] } {
  const check = results
    .filter(needsCheck)
    .sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict] || (a.moment_sec ?? 1e9) - (b.moment_sec ?? 1e9));
  const ok = results.filter((r) => !needsCheck(r));
  return { check, ok };
}

export function effectiveVerdict(r: ItemResult, d?: Decision): Verdict {
  return d && d.human ? d.human : r.verdict;
}

/** Hanya keputusan yang benar-benar mengubah verdict AI yang disimpan sebagai override. */
export function buildOverrides(results: ItemResult[], decisions: Decisions, nowIso: string): Override[] {
  const out: Override[] = [];
  for (const r of results) {
    const d = decisions[r.item_id];
    if (d && d.human && d.human !== r.verdict) {
      out.push({ item_id: r.item_id, human_verdict: d.human, note: d.note.trim(), at: nowIso });
    }
  }
  return out;
}

/** Item gagal atau ragu yang belum disentuh reviewer. */
export function unreviewedIds(results: ItemResult[], decisions: Decisions): string[] {
  return results.filter((r) => r.verdict !== "pass" && !(r.item_id in decisions)).map((r) => r.item_id);
}

function same(a: ChecklistItem, b: ChecklistItem): boolean {
  return (
    a.description === b.description &&
    a.category === b.category &&
    a.enabled === b.enabled &&
    a.severity === b.severity &&
    a.modalities.join() === b.modalities.join()
  );
}

/** Selisih antara checklist asli dan hasil edit reviewer, dalam bentuk operasi API. */
export function buildTemplateEdits(original: ChecklistItem[], current: ChecklistItem[]): TemplateEdit[] {
  const edits: TemplateEdit[] = [];
  const orig = new Map(original.map((i) => [i.id, i]));
  const now = new Map(current.map((i) => [i.id, i]));
  for (const item of current) {
    const before = orig.get(item.id);
    if (!before) edits.push({ op: "add", item });
    else if (!same(before, item)) edits.push({ op: "update", item_id: item.id, item });
  }
  for (const item of original) {
    if (!now.has(item.id)) edits.push({ op: "remove", item_id: item.id });
  }
  return edits;
}

/** ID berikutnya untuk item skenario baru: S-01, S-02, ... */
export function nextScenarioId(items: ChecklistItem[]): string {
  let max = 0;
  for (const i of items) {
    const m = /^S-(\d+)$/.exec(i.id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `S-${String(max + 1).padStart(2, "0")}`;
}
