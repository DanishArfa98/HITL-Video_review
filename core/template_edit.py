"""Menerapkan edit checklist dari reviewer ke template."""
from __future__ import annotations

from .schemas import ChecklistTemplate, ItemSource, TemplateEdit


def apply_template_edits(
    template: ChecklistTemplate, edits: list[TemplateEdit]
) -> ChecklistTemplate:
    """Kembalikan template baru (versi naik, created_by='human'). Template asli tidak diubah.

    - add: item baru; ID tidak boleh sudah ada.
    - update: ganti item dengan ID yang sama (ID tidak boleh berubah).
    - remove: hapus item skenario. Aturan universal tidak dihapus, cukup
      dinonaktifkan lewat update dengan enabled=false.
    """
    if not edits:
        return template

    items = list(template.items)

    def index_of(item_id: str) -> int:
        for i, it in enumerate(items):
            if it.id == item_id:
                return i
        raise ValueError(f"Item {item_id} tidak ada di template")

    for e in edits:
        if e.op == "add":
            assert e.item is not None
            if any(it.id == e.item.id for it in items):
                raise ValueError(f"Item {e.item.id} sudah ada")
            items.append(e.item)
        elif e.op == "update":
            assert e.item is not None
            target = e.item_id or e.item.id
            if e.item.id != target:
                raise ValueError("ID item tidak boleh diubah saat update")
            items[index_of(target)] = e.item
        else:  # remove
            assert e.item_id is not None
            idx = index_of(e.item_id)
            if items[idx].source == ItemSource.UNIVERSAL:
                raise ValueError(
                    f"Aturan universal {e.item_id} tidak bisa dihapus; nonaktifkan saja (enabled=false)"
                )
            items.pop(idx)

    return ChecklistTemplate.model_validate(
        template.model_copy(
            update={
                "items": items,
                "template_version": template.template_version + 1,
                "created_by": "human",
            }
        ).model_dump()
    )
