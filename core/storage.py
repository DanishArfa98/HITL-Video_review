"""Penyimpanan template dan hasil: file lokal (uji) atau DynamoDB (AWS).

DynamoDB tidak menerima float Python, jadi data dikonversi ke Decimal saat
ditulis dan dikembalikan ke angka biasa saat dibaca.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .schemas import ChecklistTemplate, PrescreenResult, Role, slugify


def to_dynamo(json_text: str) -> dict[str, Any]:
    """JSON string -> dict yang aman untuk DynamoDB (float jadi Decimal)."""
    return json.loads(json_text, parse_float=Decimal)


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Tipe tidak didukung: {type(value)!r}")


def from_dynamo(item: dict[str, Any]) -> dict[str, Any]:
    """Item DynamoDB -> dict biasa (Decimal jadi int atau float)."""
    return json.loads(json.dumps(item, default=_plain))


def template_key(title: str, role: Role) -> str:
    return f"{role.value}#{slugify(title)}"


class FileTemplateStore:
    """Template sebagai file JSON di folder (dipakai uji lokal)."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _path(self, title: str, role: Role) -> Path:
        return self.directory / f"{role.value}_{slugify(title)}.json"

    def get(self, title: str, role: Role) -> ChecklistTemplate | None:
        path = self._path(title, role)
        if not path.exists():
            return None
        return ChecklistTemplate.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, template: ChecklistTemplate) -> str:
        path = self._path(template.scenario_title, template.role)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.model_dump_json(indent=2), encoding="utf-8")
        return str(path)


class DynamoTemplateStore:
    """Template di tabel DynamoDB. Kunci partisi: template_id = '<peran>#<slug-judul>'."""

    def __init__(self, table: Any):
        self.table = table

    def get(self, title: str, role: Role) -> ChecklistTemplate | None:
        resp = self.table.get_item(Key={"template_id": template_key(title, role)})
        item = resp.get("Item")
        if not item:
            return None
        data = from_dynamo(item)
        data.pop("template_id", None)
        return ChecklistTemplate.model_validate(data)

    def put(self, template: ChecklistTemplate) -> str:
        key = template_key(template.scenario_title, template.role)
        item = to_dynamo(template.model_dump_json())
        item["template_id"] = key
        self.table.put_item(Item=item)
        return key


class DynamoResultStore:
    """Hasil pre-screening di tabel DynamoDB. Kunci partisi: video_id."""

    def __init__(self, table: Any):
        self.table = table

    def put(self, result: PrescreenResult) -> str:
        self.table.put_item(Item=to_dynamo(result.model_dump_json()))
        return result.video_id

    def get(self, video_id: str) -> PrescreenResult | None:
        item = self.table.get_item(Key={"video_id": video_id}).get("Item")
        return PrescreenResult.model_validate(from_dynamo(item)) if item else None
