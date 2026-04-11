#!/usr/bin/env bash
# Usage: ./release.sh v1.1 "describe what changed"
# Requires: py2app, create-dmg, git, and optionally GITHUB_TOKEN env var for auto-release

set -euo pipefail

VERSION="${1:-}"
MESSAGE="${2:-}"

if [[ -z "$VERSION" || -z "$MESSAGE" ]]; then
  echo "Usage: $0 <version> <message>"
  echo "  e.g. $0 v1.1 'add double-snap support'"
  exit 1
fi

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+ ]]; then
  echo "Error: version must start with 'v', e.g. v1.1"
  exit 1
fi

DMG_NAME="SnapMac-${VERSION}.dmg"
REPO="akashbiswas0/SnapMac"

echo "==> Building py2app..."
rm -rf build dist
python setup.py py2app 2>&1 | tail -5

echo "==> Stripping quarantine..."
xattr -cr dist/SnapMac.app

echo "==> Building DMG: $DMG_NAME"
create-dmg \
  --volname "SnapMac" \
  --window-size 500 300 \
  --icon-size 100 \
  --icon "SnapMac.app" 130 150 \
  --hide-extension "SnapMac.app" \
  --app-drop-link 370 150 \
  "$DMG_NAME" \
  "dist/"

echo "==> Committing and tagging $VERSION..."
git add .
git commit -m "${VERSION} — ${MESSAGE}"
git tag "$VERSION"
git push origin main --tags

echo "==> DMG ready: $DMG_NAME"

# ── Optional: auto-create GitHub release via API ──────────────────────────────
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  echo "==> Creating GitHub release via API..."

  RELEASE_RESPONSE=$(curl -s -X POST \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/${REPO}/releases" \
    -d "{\"tag_name\":\"${VERSION}\",\"name\":\"${VERSION}\",\"body\":\"${MESSAGE}\"}")

  UPLOAD_URL=$(echo "$RELEASE_RESPONSE" | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['upload_url'].split('{')[0])")

  if [[ -z "$UPLOAD_URL" ]]; then
    echo "Warning: could not parse upload URL. Create the release manually on GitHub."
  else
    echo "==> Uploading $DMG_NAME..."
    curl -s -X POST \
      -H "Authorization: token $GITHUB_TOKEN" \
      -H "Content-Type: application/octet-stream" \
      --data-binary @"$DMG_NAME" \
      "${UPLOAD_URL}?name=${DMG_NAME}" > /dev/null
    echo "==> Release published: https://github.com/${REPO}/releases/tag/${VERSION}"
  fi
else
  echo ""
  echo "── Manual step: publish GitHub release ──────────────────────────────────"
  echo "  1. Go to https://github.com/${REPO}/releases/new"
  echo "  2. Select tag: $VERSION"
  echo "  3. Upload: $DMG_NAME"
  echo "  4. Click 'Publish release'"
  echo ""
  echo "  Tip: set GITHUB_TOKEN env var to automate this step next time."
fi
