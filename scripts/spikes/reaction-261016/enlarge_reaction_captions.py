"""v5: bigger reaction-part captions (owner, 17/10/2026: hard to read on a phone, older viewers)."""
import re, sys
from collections import defaultdict


def enlarge_split(ass: str) -> str:
    """Natã's split captions from 92 to 128 px (the full-phase size), still riding the gold line.

    One-line screens sit at y 1000; a two-line screen keeps its lower line at 1000 and lifts the
    upper one to 896, so no line ever covers his head in the bottom panel.
    """
    ass = ass.replace("Style: Cap,Anton,92,", "Style: Cap,Anton,128,").replace(",1,0,1,5,0,2,", ",1,0,1,6,0,2,")
    lines = ass.split("\n")
    two = defaultdict(bool)
    for ln in lines:
        m = re.match(r"Dialogue: 0,([^,]+),.*\\pos\(547,1010\)", ln)
        if m:
            two[m.group(1)] = True
    out = []
    for ln in lines:
        m = re.match(r"Dialogue: 0,([^,]+),", ln)
        if m:
            if "\\pos(547,1010)" in ln:
                ln = ln.replace("\\pos(547,1010)", "\\pos(547,1000)")
            elif "\\pos(547,932)" in ln:
                ln = ln.replace("\\pos(547,932)", "\\pos(547,896)" if two[m.group(1)] else "\\pos(547,1000)")
        out.append(ln)
    return "\n".join(out)


def enlarge_orig(ass: str, size: int = 68, max_chars: int = 26) -> str:
    """The pastor's translated lines from 50 to 68 px, broken in two at the space nearest the middle
    (the file uses WrapStyle 2, so libass never wraps on its own)."""
    ass = ass.replace("Style: Orig,Raleway,50,", f"Style: Orig,Raleway,{size},")
    out = []
    for ln in ass.split("\n"):
        if ",Orig,," in ln:
            head, text = ln.rsplit("}", 1)
            if len(text) > max_chars and "\\N" not in text:
                mid = len(text) // 2
                spaces = [i for i, c in enumerate(text) if c == " "]
                k = min(spaces, key=lambda i: abs(i - mid))
                text = text[:k] + "\\N" + text[k + 1:]
            ln = head + "}" + text
        out.append(ln)
    return "\n".join(out)


if __name__ == "__main__":
    split_path, overlay_path = sys.argv[1:3]
    s = open(split_path).read(); open(split_path, "w").write(enlarge_split(s))
    o = open(overlay_path).read(); open(overlay_path, "w").write(enlarge_orig(o))
