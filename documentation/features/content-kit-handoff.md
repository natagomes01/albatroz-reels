# Handoff: Shorts to the content kit

What the content kit session receives for each finished Short, where it lives, and how to build it.

## One command

```
uv run shorts export <job>            # every approved clip that has a render
uv run shorts export <job> --dest ~/somewhere   # another folder
```

Default folder: `~/dev/albatroz-media/final/<channel>/<job>/`, one subfolder per clip, plus
`index.json` (job, channel, the list of clip folders). Run it again after a re-render: it overwrites.
The video is a hard link to the render, so nothing is copied twice on disk.

## What is in each clip folder

| File | What it holds | Use in the kit |
|---|---|---|
| `<clip>.mp4` | the 1080x1920 Short, final | the video to post |
| `clip.json` | the render's meta: `title`, `hook`, `channel`, `content_language`, `duration`, `segments`, `broll`, `credits`, `render_version`, `score` | identifies the clip (`job` + `clip_id`); title and hook are the starting point for caption and on-screen hook |
| `captions.ass` | the burned-in captions, word by word, with timings | exact on-screen text and rhythm |
| `transcript.txt` | the words of the clip as the captions show them, with the owner's fixes | base text for the written caption and the SEO |
| `context.md` | class topic, references (Provérbios 25, Salmo 22...), names and terms, hook, image credits | the context the kit needs, so the class link and a summary are enough |

## How the kit session identifies a clip

By `job` and `clip_id`, both inside `clip.json` and in the folder path
(`final/<channel>/<job>/<clip_id>/`). `index.json` lists every clip of the job. The channel and
`content_language` in `clip.json` say which profile and language to write in.

## Credits

`clip.json` has `credits` (text, empty when every image is public domain or the owner's own).
`context.md` repeats it under "Image credits". A CC BY image needs that line in the post.

## Where the rest lives (not exported)

- full class transcript: `jobs/<job>/words.json`; readable copy: `jobs/<job>/<job>.md`
- class summary: `jobs/<job>/analyze/class_sheet.json`
- why each clip was picked and its scores: `jobs/<job>/analyze/candidates.json`, `clip.json` -> `score`

## Rules for the kit

- The kit never edits the video or `clip.json`; it only reads them.
- Text for the posts is written in the channel's content language (`clip.json` -> `content_language`).
