---
name: reaction-edit
description: Playbook for editing a reaction Short (a third-party clip from Facebook or Instagram plus the owner's recorded reaction, split screen then full screen, translated captions, blurred children, cards, B-roll paintings). Use whenever the owner sends a link to react to, a reaction recording, or asks for a "React", "reação", split screen or a dynamic edit outside the class pipeline. Holds the rules learned on 16-17/10/2026 so the same sync and audio bugs never come back.
---

# Reaction edit: playbook

Learned on the first reaction Short (job `261016-stedfast`, approved as v3 on 17/10/2026).
Reference scripts: `scripts/spikes/reaction-261016/` (hard-coded to that job; copy, then edit).
Media: `<media_root>/reactions/<yymmdd-slug>/` (`media_root` from `config.toml`).

This is not yet a pipeline feature: there is no spec, no module, no tests. Until there is, run it
as a scripted edit and follow every rule below. When the owner asks to make it a feature, go
through brainstorming and a spec first (the shared layers are punch, keyword, sfx, card, transition).

## The format (as the owner approved it)

1. **Hook, about 3 s:** the most shocking moment of the original in full screen, wide then a tight
   crop at the impact, original sound, a title on top (Anton, white with one yellow phrase), the
   translated line at the bottom.
2. **Reaction, split screen:** original on top (1080x956, only the real picture, never the
   reposter's blurred bars, watermark or burned-in title), an 8 px gold line (`0xE5C76B`), the
   owner below (1080x956). Original audio sits 4 dB under his voice and ducks when he speaks
   (`sidechaincompress`). Keep only the original moments that carry the story plus every moment
   he speaks; cut his pauses. After the original ends, the top shows slow-motion replays (half
   speed) of the key blows while he keeps talking.
3. **Argument, full screen:** silences cut, framing alternates per sentence (wide, close 1.3x),
   punch-in 1.6x on the strongest phrases, cards with Bible references, one animated keyword at a
   time, cutaways to the original over his voice, B-roll paintings.
4. Cut every take error ("eu errei", "se você quer continuar...").
5. Final CTA kept in full.

Length the owner accepted: 2 min 19 s, with the full argument. He asked for the reaction part to
be short (35 s out of 54 s).

## Owner preferences (do not relitigate)

- Children's faces always blurred, the boy and the girl and any child facing the camera.
- B-roll paintings pan along ONE axis only: portrait images top to bottom, landscape images left
  to right. A diagonal pan "gives a nudge sideways and a nudge up"; he rejected it on every image.
- Mix full-screen and half-screen B-roll. In half screen, he is on top and the painting below, so
  the caption band (y 1226 to 1330) falls on the painting, not on his face.
- Captions one line per screen (`captions.SEGMENT_MAX = captions.LINE_MAX`): two-line screens
  show words before he says them and he reads that as "out of sync".
- Satan / hatred beat: Alexandre Cabanel, "The Fallen Angel" (1847), cropped on the eye with the
  tear and the arm hiding the face (`Alexandre Cabanel - Fallen Angel (cropped).jpg` on Commons).
- Zooms (close and punch) were approved as they are.
- Caption size never drops in the reaction part: the split-screen captions use the full-phase
  size. `edit.py` still writes 92 px; `enlarge_reaction_captions.py` patches the ASS files (v5).
- Log the cost of every step: tokens and machine time (see "Cost logging").

## Steps and commands

```
# 1. download (yt-dlp is installed via Homebrew)
mkdir -p <media_root>/reactions/<job> && cd $_
yt-dlp -o "original.%(ext)s" "<facebook or instagram url>"   # login-only posts: --cookies-from-browser chrome
cp <owner recording>.mov reaction.mov

# 2. transcribe both (the transcreve script that has --palavras lives in ~/dev/transcreve)
python3 ~/dev/transcreve/transcreve.py --palavras reaction.mov --prompt "<names, terms>"
python3 ~/dev/transcreve/transcreve.py --palavras original.mp4 --idioma en

# 3. offset between the two recordings (he plays the original through the speaker)
FF=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
$FF -i original.mp4 -map 0:a:0 -ac 1 -ar 8000 -f f32le orig.raw
$FF -i reaction.mov -map 0:a:0 -ac 1 -ar 8000 -f f32le reac.raw
uv run --with numpy --no-project python -I scripts/spikes/reaction-261016/find_offset.py .
```

Then faces (`faces.py`), blur (`blur.py`), the edit (`edit.py`, `DRY=1` first to print the plan),
and the checks below. The `trs` shell function points to an older script without `--palavras`;
call `~/dev/transcreve/transcreve.py` directly.

## Sync rules (each one cost a render)

1. **Find the offset by audio cross-correlation, per window.** Use a log-spectrogram correlation
   on 4 s windows of the original; trust the offset when several windows agree (261016: 0.98 s in
   three windows, score 0.63 to 0.65). Windows where his voice covers the original give garbage;
   that is expected.
2. **Render each piece as TWO files: video and audio.** One output with both streams drifts:
   `trim=0:d` lets the video keep one extra frame; `-frames:v N` makes ffmpeg stop the audio a few
   ms early; `trim=end_frame=N` after a `vstack` of seeked inputs drops frames. Write the video with
   `-frames:v N` (N = round(d * 30)) and the audio with `apad=whole_dur=d` plus `-t d`, then concat
   the video list and the audio list separately and mux. Every piece duration is a whole number of
   frames (`d = N / 30`).
3. **Check every piece:** video duration equals audio duration within 1.5 ms. Any mismatch is a
   bug, never "close enough": 33 ms per piece over 40 pieces is a visible lip-sync error.
4. **Never `amix` a dozen delayed sfx with ffmpeg.** In v2 an `amix` of ~12 `adelay` inputs plus
   `loudnorm` dropped about 40 s of the voice (4,598 audio packets instead of 6,539; holes of 3
   to 7 s). Sum the sfx in numpy on the decoded body audio, then `loudnorm,aresample=48000` in one
   ffmpeg pass. `amix` with an infinite `apad` input never ends (it hung for 11 minutes).
5. **No `timeout` on macOS.** Use the tool's own timeout or `run_in_background`; a missing command
   fails instantly with exit 127 and looks like a hang.

## Verification before telling the owner it is done

All three, on the FINAL file, not on intermediates:

1. **Packets:** `ffprobe -select_streams a:0 -show_entries packet=pts_time` gives the expected
   count (duration * 48000 / 1024) and no gap over 30 ms between packets.
2. **Loudness per second:** `astats` per 48,000 samples; any second under -35 dB that is not a
   known pause is a defect.
3. **Sync per cut:** `check_sync.py` locates 0.8 s of the final audio at every cut in the
   recording. Rows with correlation 0.6 or more must be within 5 ms (exceptions: a piece shorter
   than the 0.8 s window). **A correlation near 0 is a defect until proven silent.** In v2 I
   dismissed those rows as "quiet stretches"; they were the holes.

Whole-file whisper transcription is useless for checking sync: on a 2.5 min mixed file its word
times drift by seconds. Transcribe 4 to 5 s windows if you need to hear what is in a spot.

Then look at frames: a contact sheet of the hook, the split, every B-roll and every cutaway
(`select` frames, `xstack`). Check blur coverage frame by frame where a child bends down.

## Layout constants that worked (1080x1920 output)

| Thing | Value |
|---|---|
| original clean area (reposter's 1080x1920 frame) | y 320 to 1470; top panel crop `(0, 380, 1080, 956)` |
| owner in split | crop `(0, 230, 1080, 956)` of his 1080x1920 recording |
| full framings | wide = whole frame; close `(125, 130, 830, 1476)`; tight `(203, 230, 675, 1200)` |
| captions | split: 128 px like the full phase (owner: 92 px was hard to read on a phone, older viewers), one-line screens at y 1000 on the gold line, two-line screens at 896 and 1000; full: default style, baseline 1330 |
| translated original | Raleway bold 68, box, broken in two by hand over 26 characters (`WrapStyle: 2` never wraps), `\an8` at y 150 (split), `\an2` at y 1560 (hook) |
| cards | `\an8` at y 170, Anton 84 yellow reference + Raleway 52 quote, pop-in `\fscx70 -> 100` |
| keywords | Anton 170 yellow, `\an5` at y 300, one at a time, never with a card |
| min shot | 0.7 s; a shorter framing shot takes the look of the shot it touches |
| silence cut (full phase) | `detect_silences(noise_db=-40, min_dur=0.3)`, `build_edl(trigger=0.6, keep=0.3, keep_after_question=0.5)` |

Silence cutting at `keep=0.2` with -35 dB ate word endings ("áudio picotado").

## Face blur

Apple Vision (`shorts.vision.detect`) finds faces fine in close shots (80 px faces) and misses
them in wide shots (40 to 50 px) and when a child bends down. What worked: Vision tracks for the
close shot, hand keyframes once per second for the wide shot (read off a gridded contact sheet),
extra keyframes at 0.3 s steps where the child bends, box 190x230 for small faces, `gblur sigma=22`,
crop and overlay with piecewise-linear `t` expressions. The owner accepted small misses when the
child faces down. A real tracker is future work.

## B-roll paintings

Search Wikimedia Commons with the API (`generator=search`, `prop=imageinfo`, `iiprop=url|size|extmetadata`,
`iiextmetadatafilter=LicenseShortName`, `iiurlwidth=1920`, a User-Agent with the owner's email).
Take only Public domain; reject images with text labels (the only decent Ark of the Covenant had
English labels in the middle). Per image: window size in source pixels with the layout's aspect
(full 0.5625, half 1.1297), axis, fixed coordinate, start and end offset. Scale with
`scale=w='ceil(iw*k/2)*2':h=-2:out_range=tv` (plain `iw*k` rounds to 1079 and crop fails), and add
`format=yuv420p` to every `vstack` input.

## Cost logging

- Machine: wrap each step in `timed.sh` (wall, user CPU, peak RAM) into `costs.tsv`; log failed
  and killed runs too, by name.
- Tokens: `tokens.py <session jsonl>` at `pricing.toml` rates, split by phase markers in the user
  messages. Report as API-equivalent list price.
- 261016 reference: clean pass about 4 min of machine for 2.5 min of video (transcriptions 35 s,
  Vision 7 s, blur 15 s, edit render 3 to 3.5 min, peak RAM under 2 GB). Tokens through v3:
  US$ 9.77, most of it cache reads from re-reading a long conversation, and three extra rounds
  caused by the bugs above.

## Next (the owner's plan, 17/10/2026)

- More dynamic captions with another visual (not the class Anton style): word pop, color per
  speaker, emphasis words.
- Motion graphics: Mira for full-screen visual metaphors (opaque mp4, it records the HTML deck);
  Remotion for cards and animations that must land on a word and need alpha (ProRes 4444). The
  ffmpeg pass stays the compositor.
- Any of these becomes a feature only through brainstorming and a written spec.
