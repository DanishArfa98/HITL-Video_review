"""Ekstraksi frame berkala dengan OpenCV (hanya mengambil gambar, tanpa analisis)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    second: int
    path: Path

    @property
    def filename(self) -> str:
        return self.path.name


def extract_frames(
    video_path: str | Path,
    out_dir: str | Path,
    interval_sec: int = 5,
    max_width: int = 768,
    tail_sec: int = 10,
    tail_interval: int = 2,
) -> tuple[list[Frame], float]:
    """Ambil satu frame tiap `interval_sec` detik, simpan sebagai frame_0045.jpg.

    Memakai seek (bukan membaca semua frame satu per satu) supaya cepat.
    Frame dikecilkan ke `max_width` agar hemat token dan ukuran kiriman ke Gemini.

    Returns: (daftar Frame, durasi video dalam detik)
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Video tidak bisa dibuka: {video_path}")

    frames: list[Frame] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or total <= 0:
            raise ValueError("Metadata video tidak valid (fps atau jumlah frame nol)")
        duration = total / fps

        last_index = int(total) - 1
        seconds = set(range(0, int(duration) + 1, interval_sec))
        if tail_sec > 0:
            # Bagian akhir diambil lebih rapat (tiap tail_interval detik, sampai detik
            # terakhir): aktor keluar karakter sering terjadi setelah closing.
            seconds.update(range(max(0, int(duration) - tail_sec), int(duration) + 1, tail_interval))
        for sec in sorted(seconds):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(round(sec * fps), last_index))
            ok, img = cap.read()
            if not ok:
                log.warning("Frame detik ke-%s gagal dibaca, dilewati", sec)
                continue

            h, w = img.shape[:2]
            if w > max_width:
                img = cv2.resize(
                    img, (max_width, round(h * max_width / w)), interpolation=cv2.INTER_AREA
                )

            path = out / f"frame_{sec:04d}.jpg"
            cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frames.append(Frame(second=sec, path=path))
    finally:
        cap.release()

    return frames, duration
