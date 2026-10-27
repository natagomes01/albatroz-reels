import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "pre-commit"


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(HOOK)], cwd=repo, capture_output=True, text=True)


def test_hook_allows_small_text(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "a.md"], cwd=repo, check=True)
    assert _run_hook(repo).returncode == 0


def test_hook_blocks_media_extension(tmp_path):
    repo = _repo(tmp_path)
    (repo / "Clip.MP4").write_bytes(b"x")
    subprocess.run(["git", "add", "Clip.MP4"], cwd=repo, check=True)
    result = _run_hook(repo)
    assert result.returncode == 1 and "media file blocked" in result.stderr


def test_hook_blocks_big_file(tmp_path):
    repo = _repo(tmp_path)
    (repo / "big.bin").write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    subprocess.run(["git", "add", "big.bin"], cwd=repo, check=True)
    result = _run_hook(repo)
    assert result.returncode == 1 and "limit 5 MB" in result.stderr


def test_hook_blocks_rename_to_media(tmp_path):
    repo = _repo(tmp_path)
    (repo / "x.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   cwd=repo, check=True)
    subprocess.run(["git", "mv", "x.txt", "x.mp4"], cwd=repo, check=True)
    result = _run_hook(repo)
    assert result.returncode == 1 and "media file blocked" in result.stderr


REPO = Path(__file__).resolve().parents[1]


def _ignored(rel: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO).returncode == 0


def test_gitignore_keeps_only_review_json_under_jobs():
    assert _ignored("jobs/260927-aula/words.json")
    assert _ignored("jobs/260927-aula/clips/c07/edl.json")
    assert _ignored("jobs/260927-aula/log.jsonl")
    assert _ignored("jobs/_manual/260929-101010/captions.ass")
    assert not _ignored("jobs/260927-aula/review.json")
    assert _ignored("anything/clip.MOV") or _ignored("anything/clip.mov")
    assert not _ignored("src/shorts/clip.py")


def test_package_imports():
    import shorts

    assert shorts.__version__ == "0.1.0"
