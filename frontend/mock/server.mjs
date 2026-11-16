// API tiruan untuk mencoba dashboard tanpa AWS. Token: "demo".
// Jalankan: npm run mock  (http://localhost:8787)
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { results, template } from "./data.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8787);
const TOKEN = "demo";
const STATIC_DIR = process.env.STATIC_DIR || "";
const media = ["sample.webm", "sample.mp4"].map((f) => path.join(here, f)).find((f) => fs.existsSync(f));

const reviews = {};
const uploaded = [];
let lastReview = null;
const origin = (req) => `http://${req.headers.host}`;

function send(res, code, body, headers = {}) {
  res.writeHead(code, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*", ...headers });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}
const readBody = (req) => new Promise((r) => { const c = []; req.on("data", (d) => c.push(d)); req.on("end", () => r(Buffer.concat(c).toString())); });

function row(r) {
  const rv = reviews[r.video_id];
  return { video_id: r.video_id, scenario_id: r.scenario_id, role: r.role, status: rv ? rv.final_decision : r.status,
    summary: r.summary, processed_at: r.meta.processed_at, duration_sec: r.meta.duration_sec };
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, origin(req));
  if (req.method === "OPTIONS") return send(res, 204, "");

  if (url.pathname === "/media/sample") {
    if (!media) return send(res, 404, { detail: "no media" });
    const size = fs.statSync(media).size;
    const type = media.endsWith(".webm") ? "video/webm" : "video/mp4";
    const range = req.headers.range;
    if (range) {
      const [s, e] = range.replace("bytes=", "").split("-");
      const start = Number(s), end = e ? Number(e) : size - 1;
      res.writeHead(206, { "Content-Type": type, "Content-Range": `bytes ${start}-${end}/${size}`, "Accept-Ranges": "bytes", "Content-Length": end - start + 1 });
      return fs.createReadStream(media, { start, end }).pipe(res);
    }
    res.writeHead(200, { "Content-Type": type, "Content-Length": size, "Accept-Ranges": "bytes" });
    return fs.createReadStream(media).pipe(res);
  }
  if (url.pathname.startsWith("/s3/") && req.method === "PUT") {
    await readBody(req);
    const id = "vid_" + path.basename(url.pathname, ".mp4");
    setTimeout(() => { uploaded.push(id); }, 2500); // meniru pemrosesan pipeline
    return send(res, 200, "");
  }
  if (url.pathname === "/__last") return send(res, 200, lastReview ?? {});

  if (url.pathname === "/health") return send(res, 200, { ok: true });
  const api = ["/videos", "/uploads", "/templates"].some((p) => url.pathname.startsWith(p));
  if (api) {
    if (req.headers.authorization !== `Bearer ${TOKEN}`) return send(res, 401, { detail: "Token tidak valid" });
    if (url.pathname === "/videos" && req.method === "GET") {
      const rows = Object.values(results).map(row);
      for (const id of uploaded) rows.push({ video_id: id, scenario_id: "judul-unggahan-uji", role: "teller", status: "ai_done",
        summary: { total: 1, passed: 1, failed: 0, uncertain: 0, unlocated_item_ids: [], needs_attention: false }, processed_at: new Date().toISOString(), duration_sec: 60 });
      rows.sort((a, b) => b.processed_at.localeCompare(a.processed_at));
      return send(res, 200, rows);
    }
    const m = /^\/videos\/([^/]+)(\/review)?$/.exec(url.pathname);
    if (m && !m[2] && req.method === "GET") {
      const r = results[decodeURIComponent(m[1])];
      if (!r) return send(res, 404, { detail: "Video tidak ditemukan" });
      return send(res, 200, { result: r, review: reviews[r.video_id] ?? null,
        template: r.scenario_id === template.scenario_id ? template : null,
        video_url: media && r.source ? `${origin(req)}/media/sample` : null });
    }
    if (m && m[2] && req.method === "PUT") {
      const body = JSON.parse(await readBody(req));
      lastReview = body; reviews[m[1]] = { ...body, updated_at: new Date().toISOString() };
      return send(res, 200, { video_id: m[1], status: body.final_decision, template_version: body.template_edits.length ? 3 : null });
    }
    if (url.pathname === "/uploads" && req.method === "POST") {
      const b = JSON.parse(await readBody(req));
      const stem = b.filename.replace(/\.mp4$/i, "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
      return send(res, 200, { video_id: `vid_${stem}`, key: `uploads/${stem}.mp4`, upload_url: `${origin(req)}/s3/${stem}.mp4`,
        headers: { "Content-Type": "video/mp4", "x-amz-meta-role": b.role, "x-amz-meta-title": b.title }, expires_in: 900 });
    }
    return send(res, 404, { detail: "Tidak ditemukan" });
  }

  if (STATIC_DIR) {
    let p = url.pathname === "/" ? "/index.html" : url.pathname;
    const file = path.join(STATIC_DIR, p);
    if (file.startsWith(STATIC_DIR) && fs.existsSync(file) && fs.statSync(file).isFile()) {
      const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
      res.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream" });
      return fs.createReadStream(file).pipe(res);
    }
  }
  send(res, 404, { detail: "Tidak ditemukan" });
}).listen(PORT, () => console.log(`API tiruan di http://localhost:${PORT} (token: ${TOKEN})`));
