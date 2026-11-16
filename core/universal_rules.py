"""Aturan universal per peran (konstanta, bukan dari AI).

Tidak semua aturan berlaku untuk semua peran. ID item dijaga stabil lintas peran
(U-01 selalu 3S, U-03 selalu verifikasi KTP, dst.), sehingga peran yang tidak
memerlukan sebuah aturan cukup tidak memilikinya (mis. satpam tanpa U-03).
"""
from __future__ import annotations

from .schemas import ChecklistItem, ChecklistTemplate, ItemSource, Modality, Role, Severity

ROLE_LABELS: dict[Role, str] = {
    Role.SATPAM: "satpam (petugas keamanan)",
    Role.TELLER: "teller",
    Role.CS: "customer service",
}

_VISION, _AUDIO = Modality.VISION, Modality.AUDIO


def _item(
    item_id: str,
    category: str,
    description: str,
    modalities: list[Modality],
    severity: Severity = Severity.MAJOR,
) -> ChecklistItem:
    return ChecklistItem(
        id=item_id,
        source=ItemSource.UNIVERSAL,
        category=category,
        description=description,
        modalities=modalities,
        severity=severity,
    )


def get_universal_items(role: Role) -> list[ChecklistItem]:
    """Aturan universal yang berlaku untuk satu peran."""
    is_satpam = role == Role.SATPAM

    items = [
        _item(
            "U-01", "3S",
            "Petugas menerapkan 3S (Senyum, Salam, Sapa) kepada nasabah di awal interaksi",
            [_VISION, _AUDIO],
        ),
        _item(
            "U-02", "seragam",
            "Satpam memakai seragam satpam lengkap dan rapi"
            if is_satpam
            else "Petugas memakai seragam kerja profesional (blazer atau seragam bank)",
            [_VISION],
        ),
    ]

    # Verifikasi identitas hanya milik teller dan CS. Satpam mengecek kelengkapan
    # dokumen, dan itu dinilai sebagai item skenario (S-xx).
    if role in (Role.TELLER, Role.CS):
        items.append(
            _item(
                "U-03", "verifikasi identitas",
                "Petugas meminta dan memverifikasi KTP nasabah sebelum memproses permintaan",
                [_AUDIO, _VISION],
                Severity.CRITICAL,
            )
        )

    items.append(
        _item(
            "U-04", "bahasa",
            "Petugas berbicara dengan nada sopan dan bahasa formal tanpa kata slang",
            [_AUDIO],
        )
    )
    items.append(
        _item(
            "U-05", "closing",
            f"{'Satpam' if is_satpam else 'Petugas'} menutup layanan dengan menawarkan "
            "bantuan tambahan kepada nasabah",
            [_AUDIO],
        )
    )
    items.append(
        _item(
            "U-06", "akhir video",
            "Video berakhir bersih setelah closing: aktor tidak keluar karakter (tertawa, "
            "bicara di luar skenario, melihat ke kamera) dan tidak ada adegan di luar skenario",
            [_VISION, _AUDIO],
        )
    )
    return items


def sync_universal_items(template: ChecklistTemplate) -> tuple[ChecklistTemplate, list[str]]:
    """Tambahkan aturan universal yang belum ada di template tersimpan.

    Template lama dibuat sebelum sebuah aturan universal ada (mis. U-06). Item yang sudah
    ada dipertahankan apa adanya (termasuk hasil edit manual dan `enabled`), item yang
    belum ada ditambahkan. Mengembalikan (template, id yang ditambahkan): objek yang sama
    jika tidak ada yang perlu ditambahkan, atau salinan dengan template_version naik.
    """
    canonical = get_universal_items(template.role)
    have = {i.id: i for i in template.items}
    added = [c.id for c in canonical if c.id not in have]
    if not added:
        return template, []
    canonical_ids = {c.id for c in canonical}
    universal = [have.get(c.id, c) for c in canonical]
    others = [i for i in template.items if i.id not in canonical_ids]
    synced = template.model_copy(
        update={"items": universal + others, "template_version": template.template_version + 1}
    )
    return synced, added
