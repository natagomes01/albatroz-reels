"""Where the finished sample clips fall in the full class.

    uv run python scripts/done_ranges.py <sample-job> <full-job>

The sample is a 10 minute cut that starts mid-class ("A gente não tem esse livro do rei aqui...").
This finds the sample's opening words in the full transcript (words.json of both jobs), takes the
difference as the offset, and prints each approved clip of the sample in full-class seconds.
"""
import json
import sys
from pathlib import Path

JOBS = Path(__file__).resolve().parents[1] / "jobs"


def words(job: str) -> list[dict]:
    return json.loads((JOBS / job / "words.json").read_text())["words"]


def norm(w: dict) -> str:
    return "".join(ch for ch in w["w"].lower() if ch.isalnum())


def find_offset(sample: list[dict], full: list[dict], n: int = 12) -> float | None:
    key = [norm(w) for w in sample[:n]]
    full_keys = [norm(w) for w in full]
    best = None
    for i in range(len(full_keys) - n):
        hits = sum(a == b for a, b in zip(key, full_keys[i:i + n]))
        if hits >= n - 2 and (best is None or hits > best[0]):
            best = (hits, full[i]["t"] - sample[0]["t"])
    return None if best is None else best[1]


def main(sample_job: str, full_job: str) -> int:
    off = find_offset(words(sample_job), words(full_job))
    if off is None:
        print("opening words of the sample not found in the full transcript")
        return 1
    print(f"offset: the sample starts {off:.2f} s into the full class")
    review = json.loads((JOBS / sample_job / "review.json").read_text())["decisions"]
    for cid, d in review.items():
        if d.get("status") == "approved":
            spans = ", ".join(f"{a + off:.1f}-{b + off:.1f}" for a, b in d.get("segments") or [])
            print(f"{cid}: {spans} s in the full class")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]) if len(sys.argv) == 3 else print(__doc__) or 2)
