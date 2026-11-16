import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from core import evaluate as evaluate_mod
from core import gemini_retry as retry_mod
from core.evaluate import evaluate, reconcile
from core.frames import extract_frames
from core.pipeline import run_prescreen
from core.schemas import (
    ChecklistTemplate,
    FlaggedRange,
    ItemResult,
    LLMEvaluation,
    LLMItemResult,
    Role,
    TimelineState,
    TranscriptSegment,
    Verdict,
)
from core.timeline import build_item_result, build_summary, build_timeline, padded_range
from core.universal_rules import ROLE_LABELS, get_universal_items


@pytest.fixture
def template():
    return ChecklistTemplate(
        scenario_id="tes-skenario",
        scenario_title="Tes Skenario",
        role=Role.TELLER,
        items=get_universal_items(Role.TELLER),
    )


@pytest.fixture
def sample_video(tmp_path):
    """Video sintetis 30 detik, 10 fps, 64x48."""
    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for i in range(300):
        writer.write(np.full((48, 64, 3), i % 255, dtype=np.uint8))
    writer.release()
    return path


def _fake_client(*texts):
    """Client Gemini palsu: mengembalikan teks berurutan tiap panggilan."""
    calls = iter(texts)

    def generate_content(**kwargs):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def _item(item_id, verdict, ranges):
    return ItemResult(
        item_id=item_id,
        verdict=verdict,
        confidence=0.8,
        flagged_ranges=[FlaggedRange(start=s, end=e, source="frame") for s, e in ranges],
    )


# ---------------- timeline ----------------
def test_padded_range_clips_to_video_bounds():
    assert padded_range(2, 100) == (0.0, 7.0)
    assert padded_range(98, 100) == (93.0, 100.0)
    assert padded_range(200, 100) is None


def test_timeline_overlap_and_priority():
    results = [
        _item("U-01", Verdict.FAIL, [(35, 55)]),
        _item("U-02", Verdict.FAIL, [(50, 70)]),
        _item("U-03", Verdict.UNCERTAIN, [(60, 80)]),
        _item("U-04", Verdict.PASS, []),
    ]
    tl = build_timeline(results, 100)
    got = [(s.start, s.end, s.state.value, s.item_ids) for s in tl]
    assert got == [
        (0.0, 35.0, "clear", []),
        (35.0, 50.0, "flagged", ["U-01"]),
        (50.0, 55.0, "flagged", ["U-01", "U-02"]),
        (55.0, 70.0, "flagged", ["U-02"]),  # flagged mengalahkan uncertain
        (70.0, 80.0, "uncertain", ["U-03"]),
        (80.0, 100.0, "clear", []),
    ]


def test_timeline_all_pass_is_single_clear_segment():
    tl = build_timeline([_item("U-01", Verdict.PASS, [])], 100)
    assert len(tl) == 1 and tl[0].state == TimelineState.CLEAR and tl[0].end == 100.0


def test_timeline_zero_duration():
    assert build_timeline([], 0) == []


def test_item_result_attaches_whisper_evidence_and_frames(tmp_path):
    from core.frames import Frame

    segs = [
        TranscriptSegment(start=40.0, end=46.0, text="Baik, saya catat nama Bapak ya"),
        TranscriptSegment(start=100.0, end=105.0, text="Terima kasih atas kunjungannya"),
    ]
    frames = [Frame(s, tmp_path / f"frame_{s:04d}.jpg") for s in (35, 40, 45, 50, 100)]
    r = LLMItemResult(
        item_id="U-03", verdict=Verdict.FAIL, confidence=0.8,
        reason="KTP tidak diminta", moment_sec=42.0,
    )
    out = build_item_result(r, segs, frames, duration=120)
    assert out.moment_sec == 42.0
    assert out.flagged_ranges[0].start == 37.0 and out.flagged_ranges[0].end == 47.0
    assert out.flagged_ranges[0].source == "transcript+frame"
    assert [s.text for s in out.evidence.transcript] == ["Baik, saya catat nama Bapak ya"]
    assert out.evidence.frames == ["frame_0040.jpg", "frame_0045.jpg"]


# ---------------- evaluate ----------------
def test_reconcile_fills_missing_and_drops_unknown(template):
    ev = LLMEvaluation(results=[
        LLMItemResult(item_id="U-01", verdict=Verdict.PASS, confidence=0.9),
        LLMItemResult(item_id="U-01", verdict=Verdict.FAIL, confidence=0.9),  # duplikat
        LLMItemResult(item_id="S-99", verdict=Verdict.PASS, confidence=0.9),  # tidak dikenal
    ])
    out = reconcile(ev, template)
    assert [r.item_id for r in out] == ["U-01", "U-02", "U-03", "U-04", "U-05", "U-06"]
    assert out[0].verdict == Verdict.PASS
    assert out[1].verdict == Verdict.UNCERTAIN and out[1].confidence == 0.0


def test_evaluate_retries_on_invalid_json(template, monkeypatch):
    monkeypatch.setattr(retry_mod.time, "sleep", lambda s: None)
    good = json.dumps({"results": [
        {"item_id": "U-01", "verdict": "pass", "confidence": 0.9, "moment_sec": None}
    ]})
    client = _fake_client("ini bukan json", good)
    out = evaluate(client, template, [], [])
    assert len(out) == 6 and out[0].verdict == Verdict.PASS


# ---------------- frames ----------------
def test_extract_frames(sample_video, tmp_path):
    frames, duration = extract_frames(sample_video, tmp_path / "frames", interval_sec=5)
    assert duration == pytest.approx(30.0, abs=0.2)
    assert len(frames) >= 6
    assert frames[1].filename == "frame_0005.jpg" and frames[1].path.exists()


# ---------------- end-to-end (Gemini dan Whisper dipalsukan) ----------------
def test_pipeline_end_to_end(sample_video, template, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.transcripts.transcribe",
        lambda *a, **k: [TranscriptSegment(start=10.0, end=14.0, text="Silakan duduk, Pak, saya catat dulu")],
    )
    results = [
        {"item_id": i.id, "verdict": "pass", "confidence": 0.9, "moment_sec": "null"}
        for i in template.items
    ]
    results[2] = {
        "item_id": "U-03", "verdict": "fail", "confidence": 0.8,
        "reason": "KTP tidak diminta", "quote": "Silakan duduk, Pak, saya catat dulu",
        "moment_sec": "12.0s",  # gaya output prototipe Colab
    }
    client = _fake_client(json.dumps({"results": results}))

    result = run_prescreen(sample_video, template, client, work_dir=tmp_path / "work", video_id="vid_test")

    assert result.video_id == "vid_test" and result.scenario_id == "tes-skenario"
    assert [r.verdict.value for r in result.results].count("fail") == 1
    fail = next(r for r in result.results if r.item_id == "U-03")
    assert fail.evidence.transcript[0].text.startswith("Silakan duduk")
    flagged = [s for s in result.timeline if s.state == TimelineState.FLAGGED]
    assert len(flagged) == 1 and (flagged[0].start, flagged[0].end) == (7.0, 17.0)
    assert fail.moment_sec == 12.0
    assert result.summary.failed == 1 and result.summary.unlocated_item_ids == []
    assert result.summary.needs_attention is True
    # hasil bisa diserialisasi ulang (kontrak dengan DynamoDB/FastAPI)
    assert result.model_validate_json(result.model_dump_json()) == result


def test_evaluate_waits_longer_on_503(template, monkeypatch):
    sleeps = []
    monkeypatch.setattr(retry_mod.time, "sleep", sleeps.append)

    class FakeAPIError(Exception):
        code = 503

    good = json.dumps({"results": [{"item_id": "U-01", "verdict": "pass", "confidence": 0.9}]})
    client = _fake_client(FakeAPIError("high demand"), FakeAPIError("high demand"), good)
    out = evaluate(client, template, [], [])
    assert sleeps == [10, 20]  # jeda panjang untuk error server sementara
    assert len(out) == 6


def test_pipeline_reuses_cached_transcript(sample_video, template, tmp_path, monkeypatch):
    calls = []

    def fake_transcribe(*a, **k):
        calls.append(1)
        return [TranscriptSegment(start=1.0, end=3.0, text="Selamat pagi, selamat datang")]

    monkeypatch.setattr("core.transcripts.transcribe", fake_transcribe)
    all_pass = json.dumps({"results": [
        {"item_id": i.id, "verdict": "pass", "confidence": 0.9} for i in template.items
    ]})
    client = _fake_client(all_pass, all_pass)
    work = tmp_path / "work"

    run_prescreen(sample_video, template, client, work_dir=work)
    second = run_prescreen(sample_video, template, client, work_dir=work)

    assert len(calls) == 1  # Whisper hanya berjalan sekali
    assert (work / "transcript_base.json").exists()
    assert len(second.results) == 6


# ---------------- peran (satpam / teller / cs) ----------------
def test_universal_rules_differ_per_role():
    satpam = {i.id: i for i in get_universal_items(Role.SATPAM)}
    teller = {i.id: i for i in get_universal_items(Role.TELLER)}
    cs = {i.id: i for i in get_universal_items(Role.CS)}
    assert sorted(satpam) == ["U-01", "U-02", "U-04", "U-05", "U-06"]  # satpam tanpa verifikasi KTP
    assert sorted(teller) == sorted(cs) == ["U-01", "U-02", "U-03", "U-04", "U-05", "U-06"]
    assert "satpam" in satpam["U-02"].description.lower()
    assert "blazer" in teller["U-02"].description.lower()
    assert "teller" not in " ".join(i.description.lower() for i in teller.values())


def test_prompt_mentions_role_and_reconcile_follows_role_items():
    template = ChecklistTemplate(
        scenario_id="x", scenario_title="Satpam melayani nasabah",
        role=Role.SATPAM, items=get_universal_items(Role.SATPAM),
    )
    contents = evaluate_mod.build_contents(template, [], [])
    assert ROLE_LABELS[Role.SATPAM] in contents[0]
    assert "U-03" not in contents[0]
    out = reconcile(LLMEvaluation(results=[]), template)
    assert [r.item_id for r in out] == ["U-01", "U-02", "U-04", "U-05", "U-06"]


def test_generate_template_assigns_ids_and_role():
    from core.checklist_gen import generate_template

    payload = json.dumps({"items": [
        {"category": "dokumen", "description": "Satpam menanyakan kelengkapan dokumen persyaratan",
         "modalities": ["audio"], "severity": "major"},
        {"category": "antrean", "description": "Satpam memberi estimasi waktu antrean",
         "modalities": ["audio"], "severity": "minor"},
    ]})
    t = generate_template(
        _fake_client(payload), "Satpam melayani nasabah rekening perusahaan", Role.SATPAM
    )
    assert t.role == Role.SATPAM
    assert [i.id for i in t.items] == ["U-01", "U-02", "U-04", "U-05", "U-06", "S-01", "S-02"]
    assert t.scenario_id == "satpam-melayani-nasabah-rekening-perusahaan"


# ---------------- bukti untuk item pass + ringkasan ----------------
def test_pass_item_gets_evidence_but_no_flagged_range(tmp_path):
    from core.frames import Frame

    segs = [TranscriptSegment(start=26.0, end=33.0, text="Sudah bawa KTP, NPWP, dan NIB, Pak?")]
    frames = [Frame(s, tmp_path / f"frame_{s:04d}.jpg") for s in (25, 30, 35)]
    r = LLMItemResult(
        item_id="S-02", verdict=Verdict.PASS, confidence=0.9,
        reason="Petugas menanyakan dokumen", quote="Sudah bawa KTP, NPWP, dan NIB, Pak?",
        moment_sec=28.0,
    )
    out = build_item_result(r, segs, frames, duration=99)
    assert out.flagged_ranges == []  # pass tidak memerahkan timeline
    assert out.moment_sec == 28.0
    assert [s.text for s in out.evidence.transcript] == ["Sudah bawa KTP, NPWP, dan NIB, Pak?"]
    assert out.evidence.frames == ["frame_0025.jpg", "frame_0030.jpg"]


def test_moment_outside_video_is_ignored():
    r = LLMItemResult(item_id="U-01", verdict=Verdict.FAIL, confidence=0.9, moment_sec=500.0)
    out = build_item_result(r, [], [], duration=99)
    assert out.moment_sec is None and out.flagged_ranges == []


def test_summary_flags_items_invisible_on_timeline():
    results = [
        _item("U-01", Verdict.PASS, []),
        _item("U-02", Verdict.FAIL, [(10, 20)]),  # punya momen -> terlihat di timeline
        _item("S-02", Verdict.FAIL, []),          # langkah tidak pernah terjadi
        _item("S-03", Verdict.UNCERTAIN, []),
    ]
    s = build_summary(results)
    assert (s.total, s.passed, s.failed, s.uncertain) == (4, 1, 2, 1)
    assert s.unlocated_item_ids == ["S-02", "S-03"]
    assert s.needs_attention is True
    assert build_summary([_item("U-01", Verdict.PASS, [])]).needs_attention is False


# ---------------- bukti sesuai modalitas ----------------
def test_modalities_limit_evidence(tmp_path):
    from core.frames import Frame
    from core.schemas import Modality

    segs = [TranscriptSegment(start=40.0, end=46.0, text="Silakan duduk dulu, Pak, saya catat")]
    frames = [Frame(40, tmp_path / "frame_0040.jpg")]
    r = LLMItemResult(item_id="U-02", verdict=Verdict.FAIL, confidence=0.8, moment_sec=42.0)
    vision = build_item_result(r, segs, frames, 100, modalities=[Modality.VISION])
    assert vision.evidence.transcript == [] and vision.evidence.frames == ["frame_0040.jpg"]
    assert vision.flagged_ranges[0].source == "frame"
    audio = build_item_result(r, segs, frames, 100, modalities=[Modality.AUDIO])
    assert audio.evidence.frames == [] and len(audio.evidence.transcript) == 1
    assert audio.flagged_ranges[0].source == "transcript"


# ---------------- ASR Gemini ----------------
def _make_video_with_audio(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return None
    path = tmp_path / "audio.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=64x48:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "mpeg4", "-c:a", "aac",
         "-shortest", str(path)],
        check=True,
    )
    return path


def test_parse_clock():
    from core.asr_gemini import parse_clock

    assert parse_clock("01:05") == 65.0
    assert parse_clock("1:02:03") == 3723.0
    assert parse_clock("00:07.5") == 7.5
    assert parse_clock("7s") == 7.0
    assert parse_clock(12) == 12.0


def test_segments_from_response_sorts_clamps_and_drops_invalid():
    from core.asr_gemini import _Segment, _Transcript, segments_from_response

    data = _Transcript(segments=[
        _Segment(start="00:10", end="00:14", text="  kedua  "),
        _Segment(start="00:02", end="00:02", text="pertama"),
        _Segment(start="00:30", end="00:35", text="lewat durasi"),
        _Segment(start="00:05", end="00:06", text="   "),
    ])
    out = segments_from_response(data, duration=20.0)
    assert [s.text for s in out] == ["pertama", "kedua"]
    assert out[0].end <= out[1].start and out[1].end <= 20.0


def test_segments_from_response_rejects_all_out_of_range():
    from core.asr_gemini import _Segment, _Transcript, segments_from_response

    bad = _Transcript(segments=[_Segment(start="09:00", end="09:05", text="x")])
    try:
        segments_from_response(bad, duration=20.0)
    except ValueError:
        return
    raise AssertionError("seharusnya ValueError")


def test_transcribe_gemini_keeps_verbatim_text(tmp_path):
    from core.asr_gemini import transcribe_gemini

    video = _make_video_with_audio(tmp_path)
    if video is None:
        return  # ffmpeg tidak ada
    payload = json.dumps({"segments": [
        {"start": "00:00", "end": "00:02", "text": "Selamat pagi, Pak"},
        {"start": "00:02", "end": "00:03", "text": "Gak usah, udah cukup"},
    ]})
    out = transcribe_gemini(_fake_client(payload), video)
    assert [s.text for s in out] == ["Selamat pagi, Pak", "Gak usah, udah cukup"]
    assert out[0].start == 0.0 and out[1].end <= 4.1


def test_pipeline_with_gemini_asr_uses_separate_cache(sample_video, template, tmp_path, monkeypatch):
    calls = []

    def fake_gemini(client, video, **k):
        calls.append(1)
        return [TranscriptSegment(start=1.0, end=3.0, text="Selamat pagi, selamat datang")]

    monkeypatch.setattr("core.transcripts.transcribe_gemini", fake_gemini)
    all_pass = json.dumps({"results": [
        {"item_id": i.id, "verdict": "pass", "confidence": 0.9} for i in template.items
    ]})
    client = _fake_client(all_pass, all_pass)
    work = tmp_path / "work"
    first = run_prescreen(sample_video, template, client, work_dir=work, asr="gemini")
    run_prescreen(sample_video, template, client, work_dir=work, asr="gemini")
    assert len(calls) == 1
    assert (work / "transcript_gemini_gemini-2.5-flash.json").exists()
    assert "audio" in first.meta.models["asr"]


def test_transcript_cache_rules(tmp_path, monkeypatch):
    from core.transcripts import get_transcript

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    work = tmp_path / "w"
    work.mkdir()
    stat = video.stat()

    # cache Whisper lama (tanpa field "config") tetap dipakai
    (work / "transcript_small.json").write_text(json.dumps({
        "video": {"size": stat.st_size, "mtime": int(stat.st_mtime)},
        "segments": [{"start": 0.0, "end": 1.0, "text": "cache lama"}],
    }), encoding="utf-8")
    out = get_transcript(video, work, asr="whisper", whisper_size="small")
    assert out[0].text == "cache lama"

    # cache Gemini dibuat ulang jika prompt/model berubah
    calls = []
    monkeypatch.setattr(
        "core.transcripts.transcribe_gemini",
        lambda *a, **k: calls.append(1) or [TranscriptSegment(start=0.0, end=1.0, text="halo")],
    )
    get_transcript(video, work, asr="gemini", client=object())
    get_transcript(video, work, asr="gemini", client=object())
    assert len(calls) == 1
    monkeypatch.setattr("core.transcripts.asr_config_id", lambda model: "prompt-baru")
    get_transcript(video, work, asr="gemini", client=object())
    assert len(calls) == 2


def test_text_metrics():
    from core.textmetrics import align_offsets, keyword_hits, wer, words

    assert wer(words("a b c d"), words("a x c")) == 0.5
    hits = keyword_hits("Sudah bawa KTP dan NPWP, nanti dibantu custom service ya")
    assert hits["KTP"] and hits["NPWP"] and not hits["NIB"] and not hits["customer service"]
    ref = [TranscriptSegment(start=10.0, end=14.0, text="untuk pembukaan rekening perusahaan ya Pak")]
    hyp = [TranscriptSegment(start=12.0, end=16.0, text="untuk pembukaan rekening perusahaan ya Pak")]
    assert align_offsets(ref, hyp) == [2.0]


# ---------------- U-06, sinkronisasi template, frame akhir, prompt ----------------
def test_every_role_has_clean_ending_rule():
    for role in Role:
        assert "U-06" in [i.id for i in get_universal_items(role)]


def test_sync_universal_items_adds_missing_and_keeps_edits():
    from core.schemas import ChecklistItem, ItemSource, Modality
    from core.universal_rules import sync_universal_items

    items = [i for i in get_universal_items(Role.SATPAM) if i.id != "U-06"]
    items[0] = items[0].model_copy(update={"description": "Deskripsi hasil edit manual", "enabled": False})
    extra = ChecklistItem(
        id="S-01", source=ItemSource.SCENARIO, category="x",
        description="Item skenario", modalities=[Modality.AUDIO],
    )
    old = ChecklistTemplate(scenario_id="x", scenario_title="X", role=Role.SATPAM, items=items + [extra])
    new, added = sync_universal_items(old)
    assert added == ["U-06"] and new.template_version == old.template_version + 1
    assert [i.id for i in new.items] == ["U-01", "U-02", "U-04", "U-05", "U-06", "S-01"]
    assert new.items[0].description == "Deskripsi hasil edit manual" and new.items[0].enabled is False
    again, added_again = sync_universal_items(new)
    assert added_again == [] and again is new


def test_extract_frames_samples_the_ending_more_densely(sample_video, tmp_path):
    frames, duration = extract_frames(sample_video, tmp_path / "f1")
    seconds = [f.second for f in frames]
    tail = set(range(max(0, int(duration) - 10), int(duration) + 1, 2))
    assert tail <= set(seconds)
    assert seconds == sorted(set(seconds)) and seconds[-1] == int(duration)
    plain, _ = extract_frames(sample_video, tmp_path / "f2", tail_sec=0)
    assert [f.second for f in plain] == list(range(0, int(duration) + 1, 5))


def test_generate_template_prompt_requires_verifiable_items():
    from core.checklist_gen import generate_template

    seen = {}

    def generate_content(**kwargs):
        seen["prompt"] = kwargs["contents"]
        item = {"category": "dokumen", "description": "Satpam menanyakan kelengkapan dokumen",
                "modalities": ["audio"], "severity": "major"}
        return SimpleNamespace(text=json.dumps({"items": [item]}))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    t = generate_template(client, "Satpam melayani nasabah", Role.SATPAM)
    assert "bisa dibuktikan dari rekaman" in seen["prompt"]
    assert "Video berakhir bersih" in seen["prompt"]  # aturan universal tidak diduplikasi
    assert t.items[-1].id == "S-01"


def test_evaluator_prompt_covers_video_ending():
    assert "akhir video" in evaluate_mod.SYSTEM_INSTRUCTION


# ---- handler Lambda ----

def test_parse_event_direct_s3_and_sqs():
    import handler as h

    s3_rec = {"s3": {"bucket": {"name": "b"}, "object": {"key": "up/vid+satu.mp4"}}}
    jobs, sqs = h.parse_event({"Records": [s3_rec]})
    assert not sqs and jobs[0].key == "up/vid satu.mp4" and jobs[0].bucket == "b"

    sqs_event = {"Records": [{"eventSource": "aws:sqs", "messageId": "m1",
                              "body": json.dumps({"Records": [s3_rec]})}]}
    jobs, sqs = h.parse_event(sqs_event)
    assert sqs and jobs[0].message_id == "m1"

    jobs, _ = h.parse_event({"local_video": "/data/a.mp4", "role": "satpam", "title": "T"})
    assert jobs[0].role == "satpam"
    with pytest.raises(ValueError):
        h.parse_event({"foo": 1})


def test_handler_local_video_writes_result(sample_video, tmp_path, monkeypatch):
    import handler as h

    monkeypatch.setenv("RESULT_DIR", str(tmp_path / "res"))
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "tpl"))
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    template = ChecklistTemplate(
        scenario_id="tes", scenario_title="Tes", role=Role.SATPAM,
        items=get_universal_items(Role.SATPAM),
    )
    monkeypatch.setattr(h, "load_or_create_template", lambda *a, **k: template)

    def fake_prescreen(video, tpl, client, **kw):
        assert kw["asr"] == "gemini"
        from core.schemas import PrescreenResult, ProcessingMeta
        from datetime import datetime, timezone
        return PrescreenResult(
            video_id=kw["video_id"], scenario_id="tes", role=Role.SATPAM, template_version=1,
            meta=ProcessingMeta(duration_sec=1.0, frame_interval_sec=5,
                                models={}, processed_at=datetime.now(timezone.utc)),
            results=[], timeline=[], summary=build_summary([]),
        )

    monkeypatch.setattr(h, "run_prescreen", fake_prescreen)
    out = h.handler({"local_video": str(sample_video), "role": "satpam", "title": "Tes"},
                    client=object())
    assert not out["failed"]
    assert (tmp_path / "res" / f"{out['processed'][0]['video_id']}.json").exists()
    assert not (tmp_path / "work").exists() or not any((tmp_path / "work").iterdir())


def test_handler_sqs_reports_only_failed_messages(monkeypatch):
    import handler as h

    def boom(job, **kw):
        raise RuntimeError("gagal")

    monkeypatch.setattr(h, "process_job", boom)
    rec = lambda i: {"eventSource": "aws:sqs", "messageId": f"m{i}", "body": json.dumps(
        {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": f"k{i}.mp4"}}}]})}
    out = h.handler({"Records": [rec(1), rec(2)]}, client=object())
    assert [f["itemIdentifier"] for f in out["batchItemFailures"]] == ["m1", "m2"]


def test_handler_s3_reads_role_and_title_from_metadata(tmp_path, monkeypatch):
    import handler as h

    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    seen = {}

    class FakeS3:
        def head_object(self, Bucket, Key):
            return {"Metadata": {"role": "teller", "title": "Judul"}}

        def download_file(self, bucket, key, dest):
            Path(dest).write_bytes(b"x")

    def fake_load(client, title, role, d):
        seen["args"] = (title, role)
        raise RuntimeError("berhenti di sini")

    monkeypatch.setattr(h, "load_or_create_template", fake_load)
    job = h.Job(bucket="b", key="up/a.mp4")
    with pytest.raises(RuntimeError):
        h.process_job(job, client=object(), s3=lambda: FakeS3())
    assert seen["args"] == ("Judul", Role.TELLER)


def test_evaluator_prompt_separates_no_evidence_from_violation():
    assert "tidak ada bukti" in evaluate_mod.SYSTEM_INSTRUCTION.lower()


def test_repeat_eval_summarize_flags_unstable_items():
    import repeat_eval as r

    rows = r.summarize([{"U-01": "pass", "U-05": "pass"},
                        {"U-01": "pass", "U-05": "fail"},
                        {"U-01": "pass", "U-05": "pass"}])
    by = {i: (dict(c), s) for i, c, s in rows}
    assert by["U-01"] == ({"pass": 3}, True)
    assert by["U-05"] == ({"pass": 2, "fail": 1}, False)


def test_evaluator_is_deterministic_and_judges_only_item_text():
    assert "HANYA berdasarkan kalimat deskripsinya" in evaluate_mod.SYSTEM_INSTRUCTION


def test_evaluate_uses_temperature_zero(monkeypatch, template):
    seen = {}

    def fake(client, **kw):
        seen["t"] = kw["config"].temperature
        return []

    monkeypatch.setattr(evaluate_mod, "generate_with_retry", fake)
    evaluate(object(), template, [], [])
    assert seen["t"] == 0.0


# ---- penyimpanan DynamoDB ----

class FakeTable:
    """Meniru DynamoDB: menolak float, menyimpan per kunci partisi."""

    def __init__(self, key):
        self.key, self.items = key, {}

    @staticmethod
    def _check(v):
        if isinstance(v, float):
            raise TypeError("Float tidak didukung DynamoDB")
        if isinstance(v, dict):
            for x in v.values():
                FakeTable._check(x)
        if isinstance(v, list):
            for x in v:
                FakeTable._check(x)

    def put_item(self, Item):
        self._check(Item)
        self.items[Item[self.key]] = Item

    def get_item(self, Key):
        item = self.items.get(Key[self.key])
        return {"Item": item} if item else {}


def _satpam_template():
    return ChecklistTemplate(
        scenario_id="tes", scenario_title="Tes", role=Role.SATPAM,
        items=get_universal_items(Role.SATPAM),
    )


def test_dynamo_template_store_roundtrip_and_miss():
    from core.storage import DynamoTemplateStore

    store = DynamoTemplateStore(FakeTable("template_id"))
    assert store.get("Tes", Role.SATPAM) is None
    t = _satpam_template()
    store.put(t)
    back = store.get("Tes", Role.SATPAM)
    assert back == t
    assert store.get("Tes", Role.TELLER) is None  # peran berbeda = template berbeda


def test_dynamo_result_store_converts_floats():
    from datetime import datetime, timezone

    from core.schemas import PrescreenResult, ProcessingMeta
    from core.storage import DynamoResultStore

    result = PrescreenResult(
        video_id="vid_x", scenario_id="tes", role=Role.SATPAM, template_version=1,
        meta=ProcessingMeta(duration_sec=99.5, frame_interval_sec=5, models={},
                            processed_at=datetime.now(timezone.utc)),
        results=[ItemResult(item_id="U-01", verdict=Verdict.PASS, confidence=0.9,
                            reason="ok", moment_sec=3.5)],
        timeline=[], summary=build_summary([]),
    )
    store = DynamoResultStore(FakeTable("video_id"))
    store.put(result)  # FakeTable menolak float: lolos berarti sudah jadi Decimal
    back = store.get("vid_x")
    assert back.results[0].confidence == 0.9 and back.meta.duration_sec == 99.5


def test_load_or_create_uses_store_and_generates_once(monkeypatch):
    import core.template_store as ts
    from core.storage import DynamoTemplateStore

    calls = []
    monkeypatch.setattr(ts, "generate_template",
                        lambda c, title, role: calls.append(title) or _satpam_template())
    store = DynamoTemplateStore(FakeTable("template_id"))
    ts.load_or_create_template(object(), "Tes", Role.SATPAM, store)
    ts.load_or_create_template(object(), "Tes", Role.SATPAM, store)
    assert calls == ["Tes"]  # kedua kali memakai yang tersimpan


def test_handler_saves_result_to_dynamo_when_table_set(sample_video, tmp_path, monkeypatch):
    import handler as h
    from datetime import datetime, timezone

    from core.schemas import PrescreenResult, ProcessingMeta

    tables = {"Res": FakeTable("video_id"), "Tpl": FakeTable("template_id")}
    monkeypatch.setattr(h, "_dynamo_table", lambda name: tables[name])
    monkeypatch.setenv("RESULTS_TABLE", "Res")
    monkeypatch.setenv("TEMPLATES_TABLE", "Tpl")
    monkeypatch.setenv("RESULT_DIR", str(tmp_path / "res"))
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    import core.template_store as ts
    monkeypatch.setattr(ts, "generate_template", lambda c, title, role: _satpam_template())

    def fake_prescreen(video, tpl, client, **kw):
        return PrescreenResult(
            video_id=kw["video_id"], scenario_id="tes", role=Role.SATPAM, template_version=1,
            meta=ProcessingMeta(duration_sec=1.0, frame_interval_sec=5, models={},
                                processed_at=datetime.now(timezone.utc)),
            results=[], timeline=[], summary=build_summary([]),
        )

    monkeypatch.setattr(h, "run_prescreen", fake_prescreen)
    out = h.handler({"local_video": str(sample_video), "role": "satpam", "title": "Tes"},
                    client=object())
    assert not out["failed"]
    assert len(tables["Res"].items) == 1
    assert len(tables["Tpl"].items) == 1  # template dibuat lalu tersimpan di DynamoDB
