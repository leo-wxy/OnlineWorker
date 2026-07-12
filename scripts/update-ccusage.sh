#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <tag>" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

tag="$1"
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  echo "error: expected a version tag such as v20.0.17, got: $tag" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
submodule="$repo_root/third_party/ccusage"
pricing="$repo_root/third_party/ccusage-pricing.json"

cd "$repo_root"

if [[ ! -e "$submodule/.git" ]]; then
  git submodule update --init -- third_party/ccusage
fi

git -C "$submodule" fetch --force origin "refs/tags/$tag:refs/tags/$tag"
commit="$(git -C "$submodule" rev-parse "refs/tags/$tag^{commit}")"
git -C "$submodule" checkout --detach "$commit"

echo "ccusage tag: $tag"
echo "ccusage commit: $commit"
echo "ccusage built-in agent IDs:"
python3 scripts/sync-ccusage-sources.py

if [[ ! -f "$pricing" ]]; then
  echo "error: deterministic pricing snapshot is missing: $pricing" >&2
  exit 1
fi

CCUSAGE_PRICING_JSON_PATH="$pricing" \
  python3 -m pytest -q tests/test_ccusage_dependency.py

echo "Review the ccusage gitlink and pinned expectations before committing:"
git status --short -- .gitmodules third_party/ccusage third_party/ccusage-pricing.json \
  scripts/sync-ccusage-sources.py scripts/update-ccusage.sh tests/test_ccusage_dependency.py
