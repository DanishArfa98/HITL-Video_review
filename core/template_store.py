"""Muat atau buat template checklist, dengan penyimpanan file lokal atau DynamoDB."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .checklist_gen import generate_template
from .schemas import ChecklistTemplate, Role
from .storage import FileTemplateStore
from .universal_rules import sync_universal_items

log = logging.getLogger(__name__)


def load_or_create_template(
    client: Any, title: str, role: Role, templates: Any
) -> ChecklistTemplate:
    """Muat template untuk (peran, judul); buat dengan Gemini jika belum ada.

    `templates` boleh berupa folder (str/Path, disimpan sebagai file JSON) atau
    objek penyimpanan dengan get(title, role) dan put(template), mis. DynamoTemplateStore.
    Template lama otomatis disinkronkan dengan aturan universal terbaru.
    """
    store = FileTemplateStore(templates) if isinstance(templates, (str, Path)) else templates

    template = store.get(title, role)
    if template is not None:
        print("Memakai template tersimpan.")
        template, added = sync_universal_items(template)
        if added:
            store.put(template)
            print(f"Aturan universal baru ditambahkan ke template: {', '.join(added)}")
        return template

    print("Membuat checklist baru dengan Gemini...")
    template = generate_template(client, title, role)
    where = store.put(template)
    print(f"Template disimpan: {where}")
    return template
