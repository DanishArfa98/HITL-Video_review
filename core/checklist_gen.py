"""Pembuatan checklist skenario: judul bebas + peran -> Gemini -> ChecklistTemplate."""
from __future__ import annotations

import logging
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field

from .schemas import (
    ChecklistItem,
    ChecklistTemplate,
    ItemSource,
    Modality,
    Role,
    Severity,
    slugify,
)
from .universal_rules import ROLE_LABELS, get_universal_items

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


class _GeneratedItem(BaseModel):
    category: str
    description: str = Field(min_length=3)
    modalities: list[Modality] = Field(min_length=1)
    severity: Severity


class _GeneratedItems(BaseModel):
    items: list[_GeneratedItem]


def generate_template(
    client: Any,
    scenario_title: str,
    role: Role,
    n_items: int = 4,
    model: str = DEFAULT_MODEL,
) -> ChecklistTemplate:
    """Buat template: aturan universal untuk peran itu (konstanta) + item skenario (AI).

    ID item (S-01, S-02, ...) diberikan oleh kode, bukan oleh model, supaya stabil.
    """
    title = scenario_title.strip()
    universal = get_universal_items(role)
    universal_desc = "\n".join(f"- {i.description}" for i in universal)

    prompt = (
        f"Skenario role-play layanan bank: \"{title}\".\n"
        f"Peran petugas yang dinilai: {ROLE_LABELS[role]}.\n\n"
        f"Buat {n_items} item checklist yang spesifik untuk skenario ini. "
        "Item hanya boleh menilai tugas yang memang dilakukan oleh peran tersebut. "
        "Setiap item harus bisa dibuktikan dari rekaman video itu sendiri (ucapan atau "
        "gambar). Jangan membuat item tentang kejadian di luar rekaman (misalnya saat "
        "nasabah bertransaksi di mesin atau loket lain), niat atau perasaan petugas, "
        "atau kondisi yang tidak mungkin terlihat. "
        "Jangan menilai langkah yang menjadi tugas peran lain (misalnya bagian yang "
        "akan ditangani petugas lain setelah nasabah dirujuk). "
        "Setiap item harus bisa diverifikasi dari ucapan petugas (audio) dan/atau "
        "gambar video (vision), ditulis dalam Bahasa Indonesia formal, satu kalimat, "
        "dan berupa perilaku yang diamati (bukan opini).\n\n"
        "Jangan menduplikasi aturan universal berikut, karena sudah ada:\n"
        f"{universal_desc}"
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_GeneratedItems,
            temperature=0.3,
        ),
    )
    generated = _GeneratedItems.model_validate_json(response.text)

    scenario_items = [
        ChecklistItem(
            id=f"S-{idx:02d}",
            source=ItemSource.SCENARIO,
            category=g.category,
            description=g.description,
            modalities=g.modalities,
            severity=g.severity,
        )
        for idx, g in enumerate(generated.items, start=1)
    ]
    log.info("Checklist '%s' (%s): %d item skenario dibuat", title, role.value, len(scenario_items))

    return ChecklistTemplate(
        scenario_id=slugify(title),
        scenario_title=title,
        role=role,
        items=universal + scenario_items,
    )
