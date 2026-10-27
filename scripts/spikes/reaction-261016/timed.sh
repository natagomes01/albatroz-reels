#!/bin/zsh
# usage: timed.sh <step-name> <command...>; appends wall, user, sys seconds and peak RSS to costs.tsv
name=$1; shift
log=$(mktemp)
/usr/bin/time -l "$@" 2> >(tee $log >&2)
code=$?
python3 -I - "$name" "$log" "$code" <<'PY' >> "${COSTS:-costs.tsv}"
import re, sys
name, path, code = sys.argv[1:]
t = open(path, errors="replace").read()
m = re.search(r"([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys", t)
r = re.search(r"(\d+)\s+maximum resident set size", t)
print("\t".join([name, *(m.groups() if m else ("?", "?", "?")), str(round(int(r.group(1)) / 2**20)) if r else "?", code]))
PY
exit $code
