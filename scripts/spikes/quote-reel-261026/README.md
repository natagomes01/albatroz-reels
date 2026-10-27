# Spike: faceless quote Reel, EP 01 Saint Ambrose (reference, not pipeline code)

Approved as v4 on 26/10/2026. A recorded or synthetic voice reads a quote over public-domain paintings
and mosaics from Wikimedia Commons, with Ken Burns drift, cross-fades, word-highlight captions, a
punch-in on key words and a credit card. The playbook is the `faceless-quote-reel` skill.

- `find_images.py <out_dir>`: searches Commons for each group in `TERMS`, writes `candidates.json`,
  thumbnails and one numbered contact sheet per group.
- `make_reel.py [version]`: builds the Reel from the voice, its word times and the picks in `SHOTS`.

Both read `media_root` and `[broll] user_agent` from `config.toml`. The constants at the top of
`make_reel.py` (job, voice file, quote, credit, shots) belong to this episode: copy the folder for a
new one.
