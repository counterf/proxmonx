#!/usr/bin/env bash
# Bump version in all three source-of-truth files atomically, commit, and tag.
# Usage: ./scripts/release.sh <version>   e.g. ./scripts/release.sh 1.2.3
set -euo pipefail

VERSION="${1:?Usage: ./scripts/release.sh <version>}"

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "Error: version must be semver (e.g. 1.2.3), got: $VERSION"
  exit 1
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# sed -i '' is BSD sed syntax (macOS); script is intended to run on macOS
sed -i '' "s/__version__ = \".*\"/__version__ = \"$VERSION\"/" "$REPO_ROOT/backend/app/__init__.py"
sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/"        "$REPO_ROOT/backend/pyproject.toml"
npm --prefix "$REPO_ROOT/frontend" version "$VERSION" --no-git-tag-version --silent

git -C "$REPO_ROOT" add backend/app/__init__.py backend/pyproject.toml frontend/package.json frontend/package-lock.json
git -C "$REPO_ROOT" commit -m "chore: bump version to $VERSION"
git -C "$REPO_ROOT" tag "v$VERSION"

echo ""
echo "Version bumped to $VERSION. Push with:"
echo "  git push origin main && git push origin v$VERSION"
