import assert from "node:assert/strict";
import { test } from "node:test";

import { formatClock, frameSecond, desiredRate, seekTargetFor, stateAt } from "../src/lib/timeline";
import {
  buildOverrides,
  buildTemplateEdits,
  needsCheck,
  nextScenarioId,
  partitionItems,
  unreviewedIds,
} from "../src/lib/review";
import type { ChecklistItem, ItemResult, TimelineSegment } from "../src/types";

const item = (over: Partial<ItemResult>): ItemResult => ({
  item_id: "U-01", verdict: "pass", confidence: 1, reason: "", moment_sec: null,
  evidence: { transcript: [], frames: [] }, flagged_ranges: [], ...over,
});
const check = (over: Partial<ChecklistItem>): ChecklistItem => ({
  id: "S-01", source: "scenario", category: "x", description: "Deskripsi item", modalities: ["audio"],
  severity: "major", enabled: true, ...over,
});

const timeline: TimelineSegment[] = [
  { start: 0, end: 80, state: "clear", item_ids: [] },
  { start: 80, end: 90, state: "flagged", item_ids: ["U-05"] },
  { start: 90, end: 99.5, state: "uncertain", item_ids: ["S-02"] },
];

test("stateAt menentukan zona; di luar segmen dianggap aman", () => {
  assert.equal(stateAt(timeline, 0), "clear");
  assert.equal(stateAt(timeline, 80), "flagged");
  assert.equal(stateAt(timeline, 89.9), "flagged");
  assert.equal(stateAt(timeline, 95), "uncertain");
  assert.equal(stateAt(timeline, 200), "clear");
});

test("desiredRate: cepat hanya di zona hijau saat auto aktif", () => {
  const o = { auto: true, fast: 1.5, manual: 1 };
  assert.equal(desiredRate("clear", o), 1.5);
  assert.equal(desiredRate("flagged", o), 1);
  assert.equal(desiredRate("uncertain", o), 1);
  assert.equal(desiredRate("flagged", { ...o, auto: false, manual: 2 }), 2);
});

test("frameSecond, formatClock, seekTargetFor", () => {
  assert.equal(frameSecond("frame_0112.jpg"), 112);
  assert.equal(frameSecond("foto.png"), null);
  assert.equal(formatClock(75.9), "1:15");
  assert.equal(seekTargetFor(item({ moment_sec: 117 })), 115);
  assert.equal(seekTargetFor(item({ moment_sec: 1 })), 0);
  assert.equal(
    seekTargetFor(item({ verdict: "fail", flagged_ranges: [{ start: 10, end: 20, source: "frame" }] })),
    10,
  );
  assert.equal(seekTargetFor(item({ verdict: "fail" })), null);
});

test("partitionItems: gagal, ragu, lalu pass yang kurang yakin; sisanya lolos", () => {
  const rows = [
    item({ item_id: "U-01", verdict: "pass", confidence: 1 }),
    item({ item_id: "U-02", verdict: "pass", confidence: 0.7 }),
    item({ item_id: "S-01", verdict: "uncertain", confidence: 0.6 }),
    item({ item_id: "S-02", verdict: "fail", confidence: 1, moment_sec: 50 }),
    item({ item_id: "S-03", verdict: "fail", confidence: 1, moment_sec: 20 }),
  ];
  const { check: c, ok } = partitionItems(rows);
  assert.deepEqual(c.map((r) => r.item_id), ["S-03", "S-02", "S-01", "U-02"]);
  assert.deepEqual(ok.map((r) => r.item_id), ["U-01"]);
  assert.equal(needsCheck(rows[1]), true);
});

test("buildOverrides hanya menyimpan keputusan yang berbeda dari AI", () => {
  const rows = [
    item({ item_id: "S-01", verdict: "fail" }),
    item({ item_id: "S-02", verdict: "fail" }),
    item({ item_id: "S-03", verdict: "uncertain" }),
    item({ item_id: "U-01", verdict: "pass" }),
  ];
  const out = buildOverrides(
    rows,
    {
      "S-01": { human: "pass", note: " judul keliru " },
      "S-02": { human: null, note: "" },       // setuju AI
      "S-03": { human: "fail", note: "" },     // uncertain -> fail
      "U-01": { human: "pass", note: "" },     // sama dengan AI
    },
    "2026-11-15T00:00:00Z",
  );
  assert.deepEqual(out.map((o) => [o.item_id, o.human_verdict, o.note]), [
    ["S-01", "pass", "judul keliru"],
    ["S-03", "fail", ""],
  ]);
});

test("unreviewedIds: gagal atau ragu yang belum disentuh", () => {
  const rows = [
    item({ item_id: "S-01", verdict: "fail" }),
    item({ item_id: "S-02", verdict: "uncertain" }),
    item({ item_id: "U-01", verdict: "pass", confidence: 0.5 }),
  ];
  assert.deepEqual(unreviewedIds(rows, { "S-01": { human: null, note: "" } }), ["S-02"]);
});

test("buildTemplateEdits: add, update, remove", () => {
  const original = [check({ id: "U-01", source: "universal" }), check({ id: "S-01" }), check({ id: "S-02" })];
  const current = [
    check({ id: "U-01", source: "universal", enabled: false }),
    check({ id: "S-01" }),
    check({ id: "S-03", description: "Item baru" }),
  ];
  const edits = buildTemplateEdits(original, current);
  assert.deepEqual(edits.map((e) => (e.op === "add" ? `add:${e.item.id}` : `${e.op}:${e.item_id}`)).sort(), [
    "add:S-03",
    "remove:S-02",
    "update:U-01",
  ]);
  assert.deepEqual(buildTemplateEdits(original, original), []);
});

test("nextScenarioId", () => {
  assert.equal(nextScenarioId([check({ id: "U-01" })]), "S-01");
  assert.equal(nextScenarioId([check({ id: "S-01" }), check({ id: "S-07" })]), "S-08");
});
