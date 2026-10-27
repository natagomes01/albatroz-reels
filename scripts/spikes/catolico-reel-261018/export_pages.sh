#!/bin/sh
# Export ebook pages as 1600 px JPEGs for the Remotion ebook pass, plus a contact sheet to pick them.
# Usage: export_pages.sh <ebook.pdf> <public_dir>/ebook <page> [<page> ...]
set -e
PDF=$1; OUT=$2; shift 2
FF=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
mkdir -p "$OUT/thumbs"
pdftoppm -r 18 -jpeg "$PDF" "$OUT/thumbs/p"
$FF -v error -y -pattern_type glob -i "$OUT/thumbs/p-*.jpg" -vf "scale=105:148,pad=111:154:3:3:gray,tile=12x6" -frames:v 1 "$OUT/contact-sheet.jpg"
for p in "$@"; do
  pdftoppm -f "$p" -l "$p" -scale-to 1600 -jpeg -jpegopt quality=90 "$PDF" "$OUT/page"
done
ls "$OUT"
