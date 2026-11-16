import type {
  ReviewSubmission,
  Role,
  UploadTicket,
  VideoDetail,
  VideoRow,
} from "./types";

const KEY_TOKEN = "vr_token";
const KEY_URL = "vr_api_url";

function read(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}
function write(key: string, value: string) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* penyimpanan browser bisa diblokir; sesi tetap jalan tanpa ingatan */
  }
}

export function getSession() {
  const url = read(KEY_URL) || ((import.meta.env.VITE_API_URL as string | undefined) ?? "");
  return { url: url.replace(/\/+$/, ""), token: read(KEY_TOKEN) };
}
export function saveSession(url: string, token: string) {
  write(KEY_URL, url.trim().replace(/\/+$/, ""));
  write(KEY_TOKEN, token.trim());
}
export function clearSession() {
  write(KEY_TOKEN, "");
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request<T>(path: string, init: RequestInit = {}, session = getSession()): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${session.url}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
        ...(init.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, "Tidak bisa menghubungi server. Periksa alamat API dan koneksi Anda.");
  }
  if (res.status === 401) {
    onUnauthorized();
    throw new ApiError(401, "Token tidak valid.");
  }
  if (!res.ok) {
    let detail = `Permintaan gagal (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* body bukan JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Dipakai layar login untuk mencoba alamat dan token sebelum disimpan. */
export function verifySession(url: string, token: string) {
  return request<VideoRow[]>("/videos", {}, { url: url.replace(/\/+$/, ""), token });
}

export const listVideos = () => request<VideoRow[]>("/videos");
export const getVideo = (id: string) => request<VideoDetail>(`/videos/${encodeURIComponent(id)}`);
export const submitReview = (id: string, body: ReviewSubmission) =>
  request<{ video_id: string; status: string; template_version: number | null }>(
    `/videos/${encodeURIComponent(id)}/review`,
    { method: "PUT", body: JSON.stringify(body) },
  );

/** Minta tautan unggah, lalu kirim video langsung ke S3 dengan indikator progres. */
export async function uploadVideo(
  file: File,
  title: string,
  role: Role,
  onProgress: (fraction: number) => void,
): Promise<string> {
  const ticket = await request<UploadTicket>("/uploads", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, role, title }),
  });
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", ticket.upload_url);
    for (const [k, v] of Object.entries(ticket.headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, `Unggah ke S3 ditolak (${xhr.status}). Periksa CORS bucket.`));
    xhr.onerror = () => reject(new ApiError(0, "Unggah gagal. Periksa koneksi dan pengaturan CORS bucket S3."));
    xhr.send(file);
  });
  return ticket.video_id;
}
