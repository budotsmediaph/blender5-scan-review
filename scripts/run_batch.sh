#!/bin/zsh
# Re-runs every conversion: blender 5.x headless, one process per asset.
# Usage: ./run_batch.sh            (all)   |   ./run_batch.sh mandaue   (names matching a pattern)
ROOT="/Volumes/DISK4 5588/assets-3d-scans"; OUT="$ROOT/202609_blender5_files"
cd "$ROOT" || exit 1
while IFS=$'\t' read -r name kind up src; do
  [[ -n "$1" && "$name" != *$1* ]] && continue
  echo "== $name"
  blender -b --factory-startup -P "$OUT/scripts/convert_analyze.py" -- --src "$src" --kind $kind --up=$up --name "$name" --out "$OUT" --tmp "${TMPDIR:-/tmp}" 2>&1 | grep -E 'DONE|Error|Traceback'
done < "$OUT/scripts/batch_jobs.tsv"
