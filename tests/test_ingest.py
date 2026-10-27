# tests/test_ingest.py
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from shorts import ingest
from shorts.config import AppConfig, ChannelConfig

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="Denzinger")


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                     transcreve={"python": "/usr/bin/python3", "script": "/x/transcreve.py"})


def info(height=1080, hdr=False):
    return type("I", (), {"height": height, "width": height * 16 // 9, "duration": 600.0,
                          "is_hdr": hdr})()


def fake_transcreve(calls, fail=False):
    def runner(cmd, **kw):
        calls.append(cmd)
        if fail:
            return subprocess.CompletedProcess(cmd, 1, "", "whisper crashed")
        master = Path(cmd[2])
        out_dir = Path(cmd[cmd.index("--saida") + 1])
        (out_dir / f"{master.stem}.palavras.json").write_text(json.dumps(
            {"version": 1, "words": [{"t": 0.0, "w": "Olá.", "p": 1.0}]}), encoding="utf-8")
        (out_dir / f"{master.stem}.md").write_text("# transcript", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return runner


def test_format_guard():
    ingest.check_format("solo-seated")
    with pytest.raises(ValueError, match="phase 1b"):
        ingest.check_format("conversation")
    with pytest.raises(ValueError, match="unknown format"):
        ingest.check_format("podcast")


def test_job_id_slug(tmp_path):
    assert ingest.make_job_id(Path("/x/Catequese Permanente #1.mp4"), tmp_path / "media",
                              date(2026, 9, 27)) == "260927-catequese-permanente-1"


def test_job_id_of_a_master_already_in_place_is_its_stem(tmp_path):
    m = tmp_path / "media" / "masters"
    m.mkdir(parents=True)
    v = m / "260927-catequese-permanente-1.mov"
    v.write_bytes(b"x")
    assert ingest.make_job_id(v, tmp_path / "media", date(2026, 9, 30)) == \
        "260927-catequese-permanente-1"                    # no "260930-260927-..." prefix


def test_place_master_moves_not_copies_and_keeps_mov(tmp_path):
    v = tmp_path / "IMG_9640.MOV"
    v.write_bytes(b"x" * 100)
    dst = ingest.place_master(v, tmp_path / "media", "260927-a")
    assert dst == tmp_path / "media" / "masters" / "260927-a.mov"
    assert dst.exists() and not v.exists()


def test_place_master_keeps_file_already_in_masters(tmp_path):
    m = tmp_path / "media" / "masters"
    m.mkdir(parents=True)
    v = m / "260927-a.mov"
    v.write_bytes(b"x")
    assert ingest.place_master(v, tmp_path / "media", "260927-a") == v


def test_place_master_refuses_other_volume(tmp_path, monkeypatch):
    v = tmp_path / "in.mp4"
    v.write_bytes(b"x")
    real_stat = Path.stat

    class FakeStat:
        def __init__(self, st, dev):
            self._st, self.st_dev = st, dev

        def __getattr__(self, k):
            return getattr(self._st, k)

    def fake_stat(self, *a, **k):
        st = real_stat(self, *a, **k)
        return FakeStat(st, 1 if self.name == "in.mp4" else 2)
    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(RuntimeError, match="another volume"):
        ingest.place_master(v, tmp_path / "media", "260927-a")


def test_ingest_runs_transcreve_into_the_job_dir(tmp_path, monkeypatch):
    v = tmp_path / "aula.mov"
    v.write_bytes(b"x" * 10)
    calls, warned = [], []
    monkeypatch.setattr(ingest, "probe", lambda p: info(720))
    job = ingest.ingest(v, CH, "solo-standing", app(tmp_path), runner=fake_transcreve(calls),
                        today=date(2026, 9, 27), warn=warned.append)
    cmd = calls[0]
    assert cmd[:2] == ["/usr/bin/python3", str(Path("/x/transcreve.py"))]
    assert "--palavras" in cmd and "--prompt" in cmd
    assert cmd[cmd.index("--idioma") + 1] == "pt"            # whisper language = channel language
    assert Path(cmd[cmd.index("--saida") + 1]) == job.root   # .md and .palavras.json land in the job
    meta = json.loads(job.job_json.read_text(encoding="utf-8"))
    assert meta["channel"] == "catholic-br" and meta["format"] == "solo-standing"
    assert meta["master"].endswith("260927-aula.mov")
    assert meta["warnings"] == ["input_below_1080p"] and any("1080" in w for w in warned)
    assert job.words_json.exists()
    assert not list((tmp_path / "media" / "masters").glob("*.json"))   # nothing next to the master


def test_ingest_warns_about_hdr(tmp_path, monkeypatch):
    v = tmp_path / "aula.mov"
    v.write_bytes(b"x")
    warned = []
    monkeypatch.setattr(ingest, "probe", lambda p: info(2160, hdr=True))
    job = ingest.ingest(v, CH, "solo-standing", app(tmp_path), runner=fake_transcreve([]),
                        today=date(2026, 9, 27), warn=warned.append)
    assert json.loads(job.job_json.read_text(encoding="utf-8"))["warnings"] == ["hdr_input"]
    assert any("HDR" in w for w in warned)


def test_ingest_resumes_after_a_failed_transcription(tmp_path, monkeypatch):
    v = tmp_path / "aula.mov"
    v.write_bytes(b"x")
    monkeypatch.setattr(ingest, "probe", lambda p: info())
    a = app(tmp_path)
    with pytest.raises(RuntimeError, match="transcreve failed"):
        ingest.ingest(v, CH, "solo-standing", a, runner=fake_transcreve([], fail=True),
                      today=date(2026, 9, 27))
    master = tmp_path / "media" / "masters" / "260927-aula.mov"
    assert master.exists() and not v.exists()
    calls = []
    job = ingest.ingest(master, CH, "solo-standing", a, runner=fake_transcreve(calls),
                        today=date(2026, 9, 30))                # rerun days later, from masters/
    assert job.id == "260927-aula" and job.words_json.exists() and len(calls) == 1
    with pytest.raises(FileExistsError, match="already ingested"):
        ingest.ingest(master, CH, "solo-standing", a, runner=fake_transcreve([]),
                      today=date(2026, 9, 30))


def test_ingest_stores_the_topic_line(tmp_path, monkeypatch):
    v = tmp_path / "aula.mov"
    v.write_bytes(b"x")
    monkeypatch.setattr(ingest, "probe", lambda p: info())
    job = ingest.ingest(v, CH, "solo-standing", app(tmp_path), runner=fake_transcreve([]),
                        today=date(2026, 9, 27),
                        topic="  crítica textual do AT,\n Septuaginta vs texto massorético ")
    meta = json.loads(job.job_json.read_text(encoding="utf-8"))
    assert meta["topic"] == "crítica textual do AT, Septuaginta vs texto massorético"


def test_ingest_without_topic_stores_empty_and_resume_can_add_it(tmp_path, monkeypatch):
    v = tmp_path / "aula.mov"
    v.write_bytes(b"x")
    monkeypatch.setattr(ingest, "probe", lambda p: info())
    a = app(tmp_path)
    with pytest.raises(RuntimeError):
        ingest.ingest(v, CH, "solo-standing", a, runner=fake_transcreve([], fail=True),
                      today=date(2026, 9, 27))
    master = tmp_path / "media" / "masters" / "260927-aula.mov"
    assert json.loads((tmp_path / "jobs" / "260927-aula" / "job.json").read_text(encoding="utf-8"))["topic"] == ""
    job = ingest.ingest(master, CH, "solo-standing", a, runner=fake_transcreve([]),
                        today=date(2026, 9, 30), topic="Salmo 22")
    assert json.loads(job.job_json.read_text(encoding="utf-8"))["topic"] == "Salmo 22"


def test_clean_topic_is_one_short_line():
    assert ingest.clean_topic("a\n  b\tc") == "a b c"
    assert len(ingest.clean_topic("x" * 500)) == ingest.MAX_TOPIC == 300
    assert ingest.clean_topic(None) == ""



def test_ingest_logs_the_transcription_wall_time(tmp_path, monkeypatch):
    v = tmp_path / "aula.mov"
    v.write_bytes(b"x" * 10)
    monkeypatch.setattr(ingest, "probe", lambda p: info())
    job = ingest.ingest(v, CH, "solo-standing", app(tmp_path), runner=fake_transcreve([]),
                        today=date(2026, 9, 27), warn=lambda m: None)
    ev = [json.loads(l) for l in job.log_path.read_text(encoding="utf-8").splitlines()
          if json.loads(l)["kind"] == "transcreve"][0]
    assert isinstance(ev["wall_s"], float) and ev["wall_s"] >= 0
