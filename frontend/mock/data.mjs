// Data contoh untuk API tiruan (bentuknya sama dengan API sungguhan).
const ev = (t, s, e, text) => ({ start: s, end: e, text });
const res = (item_id, verdict, confidence, reason, moment_sec, transcript = [], frames = [], flagged_ranges = []) => ({
  item_id, verdict, confidence, reason, moment_sec, evidence: { transcript, frames }, flagged_ranges,
});

export const template = {
  scenario_id: "satpam-melayani-nasabah-yang-ingin-melakukan-penarikan-tunai",
  scenario_title: "Satpam melayani nasabah yang ingin melakukan penarikan tunai",
  role: "satpam", template_version: 2, created_by: "ai", language: "id",
  items: [
    { id: "U-01", source: "universal", category: "3S", description: "Petugas menerapkan 3S: senyum, salam, dan sapa kepada nasabah", modalities: ["vision", "audio"], severity: "major", enabled: true },
    { id: "U-02", source: "universal", category: "Penampilan", description: "Petugas mengenakan seragam satpam lengkap dan rapi", modalities: ["vision"], severity: "major", enabled: true },
    { id: "U-04", source: "universal", category: "Bahasa", description: "Petugas berbahasa formal dan sopan tanpa slang", modalities: ["audio"], severity: "major", enabled: true },
    { id: "U-05", source: "universal", category: "Closing", description: "Satpam menutup layanan dengan menawarkan bantuan tambahan kepada nasabah", modalities: ["audio"], severity: "major", enabled: true },
    { id: "U-06", source: "universal", category: "Akhir video", description: "Video berakhir bersih setelah closing: aktor tidak keluar karakter (tertawa, bicara di luar skenario, melihat ke kamera) dan tidak ada adegan di luar skenario", modalities: ["vision", "audio"], severity: "critical", enabled: true },
    { id: "S-01", source: "scenario", category: "Layanan", description: "Satpam mengarahkan nasabah ke mesin CRM untuk penarikan tunai", modalities: ["audio"], severity: "major", enabled: true },
    { id: "S-02", source: "scenario", category: "Layanan", description: "Satpam menanyakan kelengkapan dokumen atau kartu yang dibawa nasabah", modalities: ["audio"], severity: "major", enabled: true },
    { id: "S-03", source: "scenario", category: "Layanan", description: "Satpam menginformasikan jumlah antrean dan estimasi waktu tunggu kepada nasabah", modalities: ["audio"], severity: "major", enabled: true },
    { id: "S-04", source: "scenario", category: "Layanan", description: "Satpam menjaga area loket tetap tertib dan aman", modalities: ["vision"], severity: "minor", enabled: true },
  ],
};

export const results = {
  vid_ditolak1: {
    video_id: "vid_ditolak1", scenario_id: template.scenario_id, role: "satpam", template_version: 2, status: "ai_done",
    meta: { duration_sec: 118.067, processed_at: "2026-11-04T12:40:36Z", models: { asr: "gemini-2.5-flash (audio)", llm: "gemini-2.5-flash" } },
    results: [
      res("U-01", "pass", 0.7, "Petugas menyapa nasabah, tetapi senyum tidak terlalu jelas terlihat di frame.", 3, [ev(0, 3, 4, "Selamat pagi, Bapak."), ev(0, 4, 6, "Selamat datang di BRI.")], ["frame_0000.jpg", "frame_0005.jpg"]),
      res("U-02", "pass", 1, "Petugas mengenakan seragam satpam lengkap dan rapi.", 5, [], ["frame_0000.jpg", "frame_0005.jpg", "frame_0010.jpg"]),
      res("U-04", "pass", 1, "Bahasa formal dan sopan tanpa slang.", 9, [ev(0, 9, 11, "Ya, mohon maaf saya bicara dengan Bapak siapa?")]),
      res("U-05", "pass", 1, "Petugas menawarkan bantuan tambahan di akhir interaksi.", 108, [ev(0, 108, 110, "Baik, ada yang bisa dibantu lagi, Bapak Riska?")]),
      res("U-06", "fail", 1, "Petugas keluar dari karakter dengan ucapan di luar skenario dan melihat ke arah kamera sambil tersenyum di akhir video.", 117,
        [ev(0, 115, 117, "Pagi."), ev(0, 117, 118, "Aku wis arep.")], ["frame_0112.jpg", "frame_0114.jpg", "frame_0116.jpg", "frame_0118.jpg"],
        [{ start: 112, end: 118.067, source: "transcript+frame" }]),
      res("S-01", "pass", 1, "Petugas mengarahkan nasabah ke mesin CRM.", 48, [ev(0, 48, 58, "Untuk penarikan tunai bisa dilakukan di mesin CRM kami.")]),
      res("S-02", "pass", 1, "Petugas menanyakan kelengkapan dokumen.", 17, [ev(0, 17, 19, "Untuk kelengkapan dokumennya sudah dibawa?")]),
      res("S-03", "pass", 1, "Petugas menyebut dua antrean.", 65, [ev(0, 65, 73, "Antrean teller masih ada dua antrean lagi.")]),
      res("S-04", "uncertain", 0.6, "Video tidak menunjukkan area loket secara jelas untuk menilai ketertiban.", null),
    ],
    timeline: [
      { start: 0, end: 112, state: "clear", item_ids: [] },
      { start: 112, end: 118.067, state: "flagged", item_ids: ["U-06"] },
    ],
    summary: { total: 9, passed: 7, failed: 1, uncertain: 1, unlocated_item_ids: ["S-04"], needs_attention: true },
    source: { bucket: "mock", key: "uploads/ditolak1.mp4" },
  },
  vid_contoh: {
    video_id: "vid_contoh", scenario_id: "satpam-melayani-nasabah-yang-ingin-membuka-rekening-perusahaan", role: "satpam", template_version: 2, status: "ai_done",
    meta: { duration_sec: 99.556, processed_at: "2026-11-11T09:30:27Z", models: { asr: "gemini-2.5-flash (audio)", llm: "gemini-2.5-flash" } },
    results: [res("U-01", "pass", 1, "Salam dan sapa jelas.", 7, [ev(0, 7, 8, "Selamat pagi.")]), res("U-05", "pass", 1, "Menawarkan bantuan tambahan.", 85, [ev(0, 85, 86, "Ada yang bisa saya bantu lagi, Bapak?")])],
    timeline: [{ start: 0, end: 99.556, state: "clear", item_ids: [] }],
    summary: { total: 2, passed: 2, failed: 0, uncertain: 0, unlocated_item_ids: [], needs_attention: false },
    source: { bucket: "mock", key: "uploads/contoh.mp4" },
  },
  vid_setor: {
    video_id: "vid_setor", scenario_id: "satpam-melayani-nasabah-setor-tunai-ke-rekening-sendiri", role: "satpam", template_version: 1, status: "ai_done",
    meta: { duration_sec: 104, processed_at: "2026-11-12T10:32:38Z", models: {} },
    results: [res("U-01", "pass", 0.9, "Salam jelas.", 3, [ev(0, 3, 10, "Selamat pagi Bu, selamat datang.")])],
    timeline: [{ start: 0, end: 104, state: "clear", item_ids: [] }],
    summary: { total: 1, passed: 1, failed: 0, uncertain: 0, unlocated_item_ids: [], needs_attention: false },
    source: null,
  },
};
