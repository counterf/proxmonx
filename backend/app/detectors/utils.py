"""Shared utilities for detector modules."""

import re

# Only strip build hash suffixes (7+ lowercase hex chars), not pre-release identifiers.
# e.g. "1.40.0.7998-c29d4c0c8" -> "1.40.0.7998"  (hash stripped)
# but "1.41.0-rc.1" -> "1.41.0-rc.1"              (pre-release preserved)
_BUILD_HASH_RE = re.compile(r'-[0-9a-f]{7,}$')


def normalize_version(version: str, strip_v: bool = False) -> str:
    """Normalize a version string for comparison.

    - Optionally strips leading 'v' prefix (e.g. 'v4.6.3' -> '4.6.3')
    - Strips trailing build hash suffixes (7+ hex chars after a hyphen,
      e.g. '1.40.0.7998-c29d4c0c8' -> '1.40.0.7998')
    - Preserves legitimate pre-release suffixes like '1.0.0-beta.1'
    """
    if strip_v:
        version = version.lstrip("v")
    version = _BUILD_HASH_RE.sub('', version)
    return version
