#!/usr/bin/env bash
set -euo pipefail
work="$(realpath -m -- "$1")"
shift
lock="$(dirname -- "$0")/locks.json"
readarray -t values < <(python3 - "$lock" <<'PY'
import json
import sys
profile = json.load(open(sys.argv[1], encoding="utf-8"))["profile"]
for field in ("lean_asset", "lean_sha256", "mathlib_commit"):
    print(profile[field])
PY
)
mkdir -p "$work/lean"
curl --proto '=https' --fail --silent --show-error --location --max-time 240 \
  -o "$work/lean.tar.zst" "${values[0]}"
printf '%s  %s\n' "${values[1]}" "$work/lean.tar.zst" | sha256sum --check
tar --zstd -xf "$work/lean.tar.zst" -C "$work/lean" --strip-components=1
git init -q "$work/mathlib"
git -C "$work/mathlib" fetch -q --depth 1 https://github.com/leanprover-community/mathlib4.git "${values[2]}"
git -C "$work/mathlib" checkout -q --detach FETCH_HEAD
test "$(git -C "$work/mathlib" rev-parse HEAD)" = "${values[2]}"
(cd "$work/mathlib"; "$work/lean/bin/lake" exe cache get "$@")
