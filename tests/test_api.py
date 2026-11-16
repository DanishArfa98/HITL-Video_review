"""Tes API: logika (api/service.py), edit template, dan rute FastAPI (jika terpasang)."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api import service
from api.service import BadRequest, Ctx, NotFound
from core.schemas import (
    ChecklistItem,
    ChecklistTemplate,
    ItemResult,
    ItemSource,
    Modality,
    Override,
    PrescreenResult,
    ProcessingMeta,
    ReviewSubmission,
    Role,
    TemplateEdit,
    Verdict,
    VideoSource,
    slugify,
)
from core.storage import DynamoResultStore, DynamoTemplateStore
from core.template_edit import apply_template_edits
from core.timeline import build_summary
from core.universal_rules import get_universal_items


class Table:
    """Tabel DynamoDB tiruan: menolak float, mendukung get/put/scan."""

    def __init__(self, key):
        self.key, self.items = key, {}

    @staticmethod
    def _check(v):
        if isinstance(v, float):
            raise TypeError("float tidak didukung DynamoDB")
        if isinstance(v, dict):
            [Table._check(x) for x in v.values()]
        if isinstance(v, list):
            [Table._check(x) for x in v]

    def put_item(self, Item):
        self._check(Item)
        self.items[Item[self.key]] = Item

    def get_item(self, Key):
        item = self.items.get(Key[self.key])
        return {"Item": item} if item else {}

    def scan(self, **kw):
        return {"Items": list(self.items.values())}


class FakeS3:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.calls.append((op, Params, ExpiresIn))
        return f"https://s3.example/{op}/{Params['Key']}?exp={ExpiresIn}"


def make_ctx():
    return Ctx(results=Table("video_id"), reviews=Table("video_id"),
               templates=Table("template_id"), s3=FakeS3(), bucket="bkt")


def scenario_item(item_id="S-01", text="Satpam menanyakan keperluan nasabah"):
    return ChecklistItem(id=item_id, source=ItemSource.SCENARIO, category="x",
                         description=text, modalities=[Modality.AUDIO])


def make_template():
    return ChecklistTemplate(
        scenario_id="tes", scenario_title="Tes", role=Role.SATPAM,
        items=get_universal_items(Role.SATPAM) + [scenario_item()],
    )


def make_result(video_id="vid_a", processed=None, with_source=True):
    return PrescreenResult(
        video_id=video_id, scenario_id="tes", role=Role.SATPAM, template_version=1,
        meta=ProcessingMeta(duration_sec=99.5, frame_interval_sec=5, models={},
                            processed_at=processed or datetime(2026, 11, 1, tzinfo=timezone.utc)),
        results=[ItemResult(item_id="U-01", verdict=Verdict.PASS, confidence=0.9,
                            reason="ok", moment_sec=3.5),
                 ItemResult(item_id="S-01", verdict=Verdict.FAIL, confidence=1.0, reason="x")],
        timeline=[], summary=build_summary([]),
        source=VideoSource(bucket="bkt", key="uploads/a.mp4") if with_source else None,
    )


def seed(ctx, result=None):
    DynamoTemplateStore(ctx.templates).put(make_template())
    DynamoResultStore(ctx.results).put(result or make_result())


def submission(**over):
    base = dict(video_id="vid_a", reviewer="danish", final_decision="approved",
                decided_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
    base.update(over)
    return ReviewSubmission(**base)


# ---- unggah ----

def test_create_upload_builds_key_video_id_and_signed_metadata():
    ctx = make_ctx()
    out = service.create_upload(ctx, "Setor Tunai.MP4", "satpam", "Judul Uji",
                                now=datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc))
    assert out["key"] == "uploads/setor-tunai-20261113100000.mp4"
    # sama dengan aturan di handler pipeline: vid_<slug nama file tanpa ekstensi>
    assert out["video_id"] == f"vid_{slugify(Path(out['key']).stem)}"
    assert out["headers"]["x-amz-meta-role"] == "satpam"
    assert out["headers"]["x-amz-meta-title"] == "Judul Uji"
    op, params, expires = ctx.s3.calls[0]
    assert op == "put_object" and params["Metadata"] == {"role": "satpam", "title": "Judul Uji"}
    assert expires == service.UPLOAD_EXPIRES_SEC


def test_create_upload_rejects_bad_input():
    ctx = make_ctx()
    for args in [("a.mov", "satpam", "T"), ("a.mp4", "direktur", "T"),
                 ("a.mp4", "satpam", "   "), ("a.mp4", "satpam", "T" * 300)]:
        with pytest.raises(BadRequest):
            service.create_upload(ctx, *args)


def test_create_upload_strips_non_ascii_from_title():
    out = service.create_upload(make_ctx(), "a.mp4", "cs", "Layanan Café")
    assert out["headers"]["x-amz-meta-title"] == "Layanan Cafe"


# ---- daftar dan detail ----

def test_list_videos_newest_first_and_review_status_wins():
    ctx = make_ctx()
    seed(ctx, make_result("vid_old", datetime(2026, 11, 1, tzinfo=timezone.utc)))
    DynamoResultStore(ctx.results).put(
        make_result("vid_new", datetime(2026, 11, 5, tzinfo=timezone.utc)))
    service.submit_review(ctx, "vid_old", submission(video_id="vid_old", final_decision="rejected"))
    rows = service.list_videos(ctx)
    assert [r["video_id"] for r in rows] == ["vid_new", "vid_old"]
    assert [r["status"] for r in rows] == ["ai_done", "rejected"]


def test_get_video_returns_result_template_and_playback_url():
    ctx = make_ctx()
    seed(ctx)
    out = service.get_video(ctx, "vid_a")
    assert out["result"]["video_id"] == "vid_a"
    assert out["template"]["scenario_id"] == "tes"
    assert out["review"] is None
    assert out["video_url"].startswith("https://s3.example/get_object/uploads/a.mp4")
    with pytest.raises(NotFound):
        service.get_video(ctx, "vid_tidak_ada")


def test_get_video_without_source_has_no_url():
    ctx = make_ctx()
    seed(ctx, make_result(with_source=False))
    assert service.get_video(ctx, "vid_a")["video_url"] is None


# ---- review ----

def test_submit_review_saves_overrides_separately_from_ai_result():
    ctx = make_ctx()
    seed(ctx)
    ov = Override(item_id="S-01", human_verdict=Verdict.PASS, note="judul keliru",
                  at=datetime(2026, 11, 2, tzinfo=timezone.utc))
    out = service.submit_review(ctx, "vid_a", submission(overrides=[ov]))
    assert out["status"] == "approved"
    detail = service.get_video(ctx, "vid_a")
    assert detail["review"]["overrides"][0]["human_verdict"] == "pass"
    assert detail["result"]["results"][1]["verdict"] == "fail"  # hasil AI tidak berubah


def test_submit_review_validations():
    ctx = make_ctx()
    seed(ctx)
    with pytest.raises(BadRequest):
        service.submit_review(ctx, "vid_a", submission(video_id="vid_lain"))
    with pytest.raises(NotFound):
        service.submit_review(ctx, "vid_x", submission(video_id="vid_x"))
    bad = Override(item_id="S-09", human_verdict=Verdict.PASS,
                   at=datetime(2026, 11, 2, tzinfo=timezone.utc))
    with pytest.raises(BadRequest):
        service.submit_review(ctx, "vid_a", submission(overrides=[bad]))


def test_submit_review_applies_template_edits_and_bumps_version():
    ctx = make_ctx()
    seed(ctx)
    edit = TemplateEdit(op="update", item_id="S-01",
                        item=scenario_item("S-01", "Satpam mengarahkan nasabah ke teller"))
    out = service.submit_review(ctx, "vid_a", submission(template_edits=[edit]))
    assert out["template_version"] == 2
    saved = DynamoTemplateStore(ctx.templates).get("tes", Role.SATPAM)
    assert saved.created_by == "human"
    assert [i for i in saved.items if i.id == "S-01"][0].description.endswith("teller")


def test_get_template_by_role_and_scenario():
    ctx = make_ctx()
    seed(ctx)
    assert service.get_template(ctx, "satpam", "tes")["role"] == "satpam"
    with pytest.raises(NotFound):
        service.get_template(ctx, "teller", "tes")
    with pytest.raises(BadRequest):
        service.get_template(ctx, "direktur", "tes")


# ---- edit template ----

def test_apply_template_edits_add_update_remove():
    t = make_template()
    out = apply_template_edits(t, [
        TemplateEdit(op="add", item=scenario_item("S-02", "Satpam memberi nomor antrean")),
        TemplateEdit(op="remove", item_id="S-01"),
    ])
    ids = [i.id for i in out.items]
    assert "S-02" in ids and "S-01" not in ids
    assert out.template_version == t.template_version + 1
    assert t.template_version == 1  # template asli tidak berubah


def test_apply_template_edits_rejects_invalid_changes():
    t = make_template()
    with pytest.raises(ValueError):  # ID ganda
        apply_template_edits(t, [TemplateEdit(op="add", item=scenario_item("S-01"))])
    with pytest.raises(ValueError):  # aturan universal tidak boleh dihapus
        apply_template_edits(t, [TemplateEdit(op="remove", item_id="U-01")])
    with pytest.raises(ValueError):  # item tidak ada
        apply_template_edits(t, [TemplateEdit(op="remove", item_id="S-09")])
    with pytest.raises(ValueError):  # ID tidak boleh berubah
        apply_template_edits(t, [TemplateEdit(op="update", item_id="S-01",
                                              item=scenario_item("S-02"))])


def test_universal_rule_can_be_disabled_via_update():
    t = make_template()
    u1 = [i for i in t.items if i.id == "U-01"][0]
    out = apply_template_edits(t, [TemplateEdit(
        op="update", item_id="U-01", item=u1.model_copy(update={"enabled": False}))])
    assert [i for i in out.items if i.id == "U-01"][0].enabled is False


# ---- handler pipeline menyimpan sumber video ----

def test_pipeline_handler_records_s3_source(tmp_path, monkeypatch):
    import handler as h

    tables = {"Res": Table("video_id"), "Tpl": Table("template_id")}
    monkeypatch.setattr(h, "_dynamo_table", lambda name: tables[name])
    monkeypatch.setenv("RESULTS_TABLE", "Res")
    monkeypatch.setenv("TEMPLATES_TABLE", "Tpl")
    monkeypatch.setenv("RESULT_DIR", str(tmp_path / "res"))
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    DynamoTemplateStore(tables["Tpl"]).put(make_template())

    class S3:
        def head_object(self, Bucket, Key):
            return {"Metadata": {"role": "satpam", "title": "Tes"}}

        def download_file(self, bucket, key, dest):
            Path(dest).write_bytes(b"x")

    monkeypatch.setattr(h, "run_prescreen",
                        lambda video, tpl, client, **kw: make_result(kw["video_id"], with_source=False))
    out = h.handler({"Records": [{"s3": {"bucket": {"name": "bkt"},
                                         "object": {"key": "uploads/a-20261113.mp4"}}}]},
                    client=object(), s3=lambda: S3())
    assert not out["failed"]
    saved = DynamoResultStore(tables["Res"]).get(out["processed"][0]["video_id"])
    assert saved.source == VideoSource(bucket="bkt", key="uploads/a-20261113.mp4")


# ---- rute FastAPI (hanya jika fastapi dan httpx terpasang) ----

try:
    from fastapi.testclient import TestClient  # noqa: F401
    HAVE_FASTAPI = True
except Exception:
    HAVE_FASTAPI = False

if HAVE_FASTAPI:
    def _client(monkeypatch, token="rahasia"):
        from api import main

        ctx = make_ctx()
        seed(ctx)
        main.app.dependency_overrides[main.get_ctx] = lambda: ctx
        if token:
            monkeypatch.setenv("API_TOKEN", token)
        return TestClient(main.app), ctx

    def test_routes_require_token(monkeypatch):
        client, _ = _client(monkeypatch)
        assert client.get("/health").status_code == 200
        assert client.get("/videos").status_code == 401
        assert client.get("/videos", headers={"Authorization": "Bearer salah"}).status_code == 401
        ok = client.get("/videos", headers={"Authorization": "Bearer rahasia"})
        assert ok.status_code == 200 and ok.json()[0]["video_id"] == "vid_a"

    def test_routes_fail_closed_without_configured_token(monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False) if hasattr(monkeypatch, "delenv") else None
        client, _ = _client(monkeypatch, token=None)
        r = client.get("/videos", headers={"Authorization": "Bearer apa-saja"})
        assert r.status_code in (401, 500)

    def test_routes_map_errors_to_http_codes(monkeypatch):
        client, _ = _client(monkeypatch)
        h = {"Authorization": "Bearer rahasia"}
        assert client.get("/videos/vid_tidak_ada", headers=h).status_code == 404
        assert client.post("/uploads", headers=h,
                           json={"filename": "a.mov", "role": "satpam", "title": "T"}).status_code == 400
