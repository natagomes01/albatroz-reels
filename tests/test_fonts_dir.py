"""The review page's fonts share assets/fonts/ with the captions (spec 6.4): libass loads every
file in that folder, so adding Raleway and Plex Mono must not change how Anton captions render."""
import hashlib
import shutil
import subprocess
from pathlib import Path

from conftest import needs_ffmpeg
from shorts.ffmpeg import FFMPEG
from shorts.render import _quote

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Bold
Style: Default,Anton,90,&H00FFFFFF,0

[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:00.50,Default,TEST 123
"""


def _frame_md5(ass: Path, fonts_dir: Path) -> str:
    out = subprocess.run(
        [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=black:s=1080x1920:d=0.5",
         "-vf", f"subtitles=filename={_quote(ass)}:fontsdir={_quote(fonts_dir)}",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True).stdout
    assert len(out) == 1080 * 1920 * 3
    return hashlib.md5(out).hexdigest()


@needs_ffmpeg
def test_new_fonts_do_not_change_caption_rendering(tmp_path):
    ass = tmp_path / "t.ass"
    ass.write_text(ASS, encoding="utf-8")
    only_anton = tmp_path / "only-anton"
    only_anton.mkdir()
    shutil.copy(FONTS / "Anton-Regular.ttf", only_anton)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _frame_md5(ass, only_anton) == _frame_md5(ass, FONTS)
    assert _frame_md5(ass, only_anton) != _frame_md5(ass, empty)   # the check can see a font change
