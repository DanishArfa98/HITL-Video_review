"""Skema data pipeline review video (v1.0).

Tiga kelompok model:
1. Template checklist   -> disimpan di DynamoDB per skenario
2. Hasil AI             -> LLMEvaluation (apa yang dikembalikan Gemini)
                           PrescreenResult (apa yang ditulis Lambda ke DynamoDB)
3. Review manusia       -> ReviewSubmission (ditulis FastAPI)

Prinsip: Gemini hanya mengembalikan penilaian per item. Bukti transkrip,
rentang waktu, dan timeline dihitung di Python, bukan oleh LLM.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Seconds = Annotated[float, Field(ge=0.0)]
ITEM_ID_PATTERN = r"^[US]-\d{2,}$"  # U-01 (universal), S-01 (skenario)


# --------------------------------------------------------------------------
# Enum
# --------------------------------------------------------------------------
class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class Role(str, Enum):
    """Peran petugas yang dinilai di video. Menentukan aturan universal yang berlaku."""

    SATPAM = "satpam"
    TELLER = "teller"
    CS = "cs"


class Severity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class Modality(str, Enum):
    AUDIO = "audio"
    VISION = "vision"


class ItemSource(str, Enum):
    UNIVERSAL = "universal"
    SCENARIO = "scenario"


class TimelineState(str, Enum):
    CLEAR = "clear"
    UNCERTAIN = "uncertain"
    FLAGGED = "flagged"


class VideoStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    AI_DONE = "ai_done"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"


# --------------------------------------------------------------------------
# Helper
# --------------------------------------------------------------------------
def slugify(title: str) -> str:
    """'Membuka Rekening Tabungan' -> 'membuka-rekening-tabungan'."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not text:
        raise ValueError("Judul skenario tidak menghasilkan slug yang valid")
    return text


def parse_seconds(value: object) -> Optional[float]:
    """Normalisasi timestamp longgar dari LLM: 90, '90.0s', 'null', '' -> float | None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in {"", "null", "none", "n/a", "-"}:
        return None
    text = text.removesuffix("s").strip()
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"Timestamp tidak valid: {value!r}")


# --------------------------------------------------------------------------
# 1. Template checklist
# --------------------------------------------------------------------------
class ChecklistItem(BaseModel):
    id: str = Field(pattern=ITEM_ID_PATTERN)
    source: ItemSource
    category: str
    description: str = Field(min_length=3)
    modalities: list[Modality] = Field(min_length=1)
    severity: Severity = Severity.MAJOR
    enabled: bool = True


class ChecklistTemplate(BaseModel):
    schema_version: str = SCHEMA_VERSION
    scenario_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    scenario_title: str
    role: Role
    template_version: int = Field(ge=1, default=1)
    language: str = "id"
    created_by: Literal["ai", "human"] = "ai"
    items: list[ChecklistItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_item_ids(self) -> "ChecklistTemplate":
        ids = [i.id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("ID item checklist harus unik")
        return self


# --------------------------------------------------------------------------
# 2a. Output mentah Gemini (dipakai sebagai response_schema + validasi)
# --------------------------------------------------------------------------
class LLMItemResult(BaseModel):
    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    verdict: Verdict
    confidence: Confidence
    reason: str = ""  # wajib Bahasa Indonesia (atur di prompt)
    quote: Optional[str] = None  # kutipan transkrip yang mendukung penilaian
    # Detik paling relevan sebagai bukti: saat perilaku terlihat (pass) atau saat
    # masalah terjadi (fail/uncertain). None jika tidak ada momen spesifik.
    moment_sec: Optional[Seconds] = None

    @field_validator("moment_sec", mode="before")
    @classmethod
    def _normalize_ts(cls, v: object) -> Optional[float]:
        return parse_seconds(v)


class LLMEvaluation(BaseModel):
    results: list[LLMItemResult]


# --------------------------------------------------------------------------
# 2b. Hasil pre-screening (ditulis Lambda ke DynamoDB)
# --------------------------------------------------------------------------
class TranscriptSegment(BaseModel):
    start: Seconds
    end: Seconds
    text: str


class TimeRange(BaseModel):
    start: Seconds
    end: Seconds

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end <= self.start:
            raise ValueError("end harus lebih besar dari start")
        return self


class FlaggedRange(TimeRange):
    source: Literal["transcript", "frame", "transcript+frame"]


class Evidence(BaseModel):
    transcript: list[TranscriptSegment] = []
    frames: list[str] = []  # contoh: "frame_0045.jpg"


class ItemResult(BaseModel):
    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    verdict: Verdict
    confidence: Confidence
    reason: str = ""
    moment_sec: Optional[Seconds] = None  # titik lompat untuk reviewer (bukti atau kesalahan)
    evidence: Evidence = Evidence()
    flagged_ranges: list[FlaggedRange] = []


class TimelineSegment(TimeRange):
    state: TimelineState
    item_ids: list[str] = []


class ProcessingMeta(BaseModel):
    duration_sec: Seconds
    frame_interval_sec: int = 5
    models: dict[str, str]
    processed_at: datetime


class ResultSummary(BaseModel):
    """Ringkasan untuk banner dashboard.

    `unlocated_item_ids` berisi item fail/uncertain yang tidak punya momen waktu
    (mis. langkah yang tidak pernah dilakukan). Item ini tidak terlihat di heatmap,
    jadi dashboard harus menampilkannya terpisah agar tidak terlewat.
    """

    total: int
    passed: int
    failed: int
    uncertain: int
    unlocated_item_ids: list[str] = []
    needs_attention: bool


class VideoSource(BaseModel):
    """Lokasi video asli di S3, dipakai API untuk membuat tautan pemutaran."""

    bucket: str
    key: str


class PrescreenResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    video_id: str
    scenario_id: str
    role: Optional[Role] = None  # None untuk hasil lama sebelum konsep peran ada
    template_version: int = Field(ge=1)
    status: VideoStatus = VideoStatus.AI_DONE
    meta: ProcessingMeta
    results: list[ItemResult]
    timeline: list[TimelineSegment]
    summary: Optional[ResultSummary] = None  # None untuk hasil lama
    source: Optional[VideoSource] = None  # None untuk hasil dari uji lokal

    @model_validator(mode="after")
    def _unique_results(self) -> "PrescreenResult":
        ids = [r.item_id for r in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("Satu item hanya boleh punya satu hasil")
        return self


# --------------------------------------------------------------------------
# 3. Review manusia (ditulis FastAPI)
# --------------------------------------------------------------------------
class Override(BaseModel):
    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    human_verdict: Literal[Verdict.PASS, Verdict.FAIL]
    note: str = ""
    at: datetime


class TemplateEdit(BaseModel):
    op: Literal["add", "remove", "update"]
    item_id: Optional[str] = Field(default=None, pattern=ITEM_ID_PATTERN)
    item: Optional[ChecklistItem] = None

    @model_validator(mode="after")
    def _check_payload(self) -> "TemplateEdit":
        if self.op in {"add", "update"} and self.item is None:
            raise ValueError(f"op '{self.op}' membutuhkan field 'item'")
        if self.op == "remove" and self.item_id is None:
            raise ValueError("op 'remove' membutuhkan field 'item_id'")
        return self


class ReviewSubmission(BaseModel):
    video_id: str
    reviewer: str
    overrides: list[Override] = []
    final_decision: Literal["approved", "rejected"]
    decided_at: datetime
    template_edits: list[TemplateEdit] = []
