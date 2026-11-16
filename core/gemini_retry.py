"""Pemanggilan Gemini dengan retry, dipakai bersama oleh evaluasi dan transkripsi."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

TRANSIENT_CODES = {429, 500, 503, 504}


def wait_seconds(error: Exception, attempt: int) -> int:
    """Jeda sebelum mencoba lagi. Error server sementara (503 sibuk, 429 kuota)
    butuh jeda jauh lebih panjang daripada JSON yang rusak."""
    if getattr(error, "code", None) in TRANSIENT_CODES:
        return min(60, 10 * 2 ** (attempt - 1))  # 10, 20, 40, 60 detik
    return 2**attempt


def generate_with_retry(
    client: Any,
    *,
    model: str,
    contents: Any,
    config: Any,
    parse: Callable[[str | None], T],
    what: str,
    max_attempts: int = 5,
) -> T:
    """Panggil generate_content lalu `parse(response.text)`.

    Kegagalan di panggilan maupun di parse (JSON rusak, validasi gagal) sama-sama
    memicu percobaan ulang.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            return parse(response.text)
        except Exception as e:  # rate limit, server sibuk, JSON/validasi tidak valid
            last_error = e
            if attempt < max_attempts:
                wait = wait_seconds(e, attempt)
                log.warning(
                    "%s percobaan %d/%d gagal (%s). Menunggu %d detik lalu mencoba lagi.",
                    what, attempt, max_attempts, e, wait,
                )
                time.sleep(wait)
            else:
                log.warning("%s percobaan %d/%d gagal (%s).", what, attempt, max_attempts, e)

    raise RuntimeError(
        f"{what} gagal setelah {max_attempts} percobaan. Error terakhir: {last_error}. "
        "Jika penyebabnya 503/429, tunggu beberapa menit lalu jalankan ulang "
        "(transkrip yang sudah dibuat tersimpan dan tidak diulang)."
    ) from last_error
