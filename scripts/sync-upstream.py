#!/usr/bin/env python3
"""Sync vendored upstream files and 3-way merge into derived files.

Reads .github/upstream-sources.yaml, downloads each tracked upstream file, and
for entries that declare a `derived` path performs a git-style 3-way merge:

    base   = previous vendored copy (what we last saw upstream)
    theirs = newly fetched upstream
    ours   = current derived file

The merge result replaces the derived file. If conflict markers remain, the
script records the source as needing manual review but keeps going so the PR
shows every change in one batch.

Outputs:
- Updated vendor files in upstream/
- Updated derived files (possibly with conflict markers)
- A summary written to $GITHUB_STEP_SUMMARY (if set) and stdout
- A machine-readable summary at sync-summary.json for the workflow to consume

Exits 0 even when there are conflicts; the workflow inspects sync-summary.json
to decide whether to mark the PR as draft.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / ".github" / "upstream-sources.yaml"
SUMMARY_PATH = REPO_ROOT / "sync-summary.json"


@dataclass
class Source:
    name: str
    url: str
    vendor: Path
    derived: Path | None = None


@dataclass
class Result:
    name: str
    vendor_changed: bool = False
    derived_changed: bool = False
    derived_conflicts: bool = False
    skipped_reason: str | None = None
    notes: list[str] = field(default_factory=list)


def load_sources(path: Path) -> list[Source]:
    """Parse the upstream-sources.yaml config without depending on PyYAML.

    The schema is intentionally simple: a top-level `sources:` list of mappings
    with `name`, `url`, `vendor`, optional `derived`. Comments (#...) and blank
    lines are ignored. Values are bare strings (no quoting required).
    """
    sources: list[Source] = []
    current: dict[str, str] | None = None
    in_sources = False

    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if line.startswith("sources:"):
            in_sources = True
            continue
        if not in_sources:
            continue

        if line.startswith("  - "):
            if current is not None:
                sources.append(_finalize(current))
            current = {}
            line = "    " + line[4:]

        m = re.match(r"^    ([a-zA-Z_]+):\s*(.+)$", line)
        if not m:
            raise ValueError(f"Unparsable config line: {raw_line!r}")
        if current is None:
            raise ValueError(f"Config key outside list item: {raw_line!r}")
        key, value = m.group(1), m.group(2).strip()
        current[key] = value

    if current is not None:
        sources.append(_finalize(current))

    if not sources:
        raise ValueError(f"No sources found in {path}")
    return sources


def _finalize(entry: dict[str, str]) -> Source:
    for required in ("name", "url", "vendor"):
        if required not in entry:
            raise ValueError(f"Source entry missing {required!r}: {entry}")
    derived = entry.get("derived")
    return Source(
        name=entry["name"],
        url=entry["url"],
        vendor=REPO_ROOT / entry["vendor"],
        derived=(REPO_ROOT / derived) if derived else None,
    )


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "athom-esp32-configs-sync"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (urlopen of trusted config URL)
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} fetching {url}")
        return resp.read()


def three_way_merge(base: Path, ours: Path, theirs_bytes: bytes) -> tuple[bytes, bool]:
    """Run `git merge-file -p` and return (merged_bytes, has_conflicts).

    Writes theirs to a temp file so git can diff against it. The vendored
    `base` and the current `ours` are passed straight through.
    """
    theirs_path = ours.parent / f".{ours.name}.theirs"
    theirs_path.write_bytes(theirs_bytes)
    try:
        proc = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "-L", "ours (customized)",
                "-L", "base (previous upstream)",
                "-L", "theirs (new upstream)",
                str(ours),
                str(base),
                str(theirs_path),
            ],
            capture_output=True,
            check=False,
        )
    finally:
        theirs_path.unlink(missing_ok=True)

    # git merge-file returns the number of remaining conflicts as exit code,
    # or -1 on error. stdout has the merged content.
    if proc.returncode < 0:
        raise RuntimeError(
            f"git merge-file failed: rc={proc.returncode} stderr={proc.stderr.decode(errors='replace')}"
        )
    return proc.stdout, proc.returncode > 0


def sync_source(source: Source, *, bootstrap: bool) -> Result:
    result = Result(name=source.name)
    try:
        new_bytes = fetch(source.url)
    except Exception as exc:  # noqa: BLE001 (surfaced in summary)
        result.skipped_reason = f"fetch failed: {exc}"
        return result

    source.vendor.parent.mkdir(parents=True, exist_ok=True)
    vendor_existed = source.vendor.exists()
    old_vendor_bytes = source.vendor.read_bytes() if vendor_existed else b""

    if not vendor_existed and not bootstrap:
        result.skipped_reason = (
            f"vendor file {source.vendor.relative_to(REPO_ROOT)} missing; "
            "re-run with --bootstrap to seed it"
        )
        return result

    if new_bytes != old_vendor_bytes:
        source.vendor.write_bytes(new_bytes)
        result.vendor_changed = True

    if source.derived is None:
        return result

    if not source.derived.exists():
        result.notes.append(
            f"derived {source.derived.relative_to(REPO_ROOT)} missing; left untouched"
        )
        return result

    if not vendor_existed:
        # Bootstrapping a new source: we have no prior base to merge against,
        # so leave the derived file alone and rely on user review.
        result.notes.append("bootstrapped vendor; derived left untouched")
        return result

    if not result.vendor_changed:
        # No upstream change → nothing to propagate.
        return result

    ours_bytes = source.derived.read_bytes()
    # Use the old vendor copy as the base for the 3-way merge.
    base_path = source.vendor.parent / f".{source.vendor.name}.base"
    base_path.write_bytes(old_vendor_bytes)
    try:
        merged, has_conflicts = three_way_merge(base_path, source.derived, new_bytes)
    finally:
        base_path.unlink(missing_ok=True)

    if merged != ours_bytes:
        source.derived.write_bytes(merged)
        result.derived_changed = True
    if has_conflicts:
        result.derived_conflicts = True
        result.notes.append("conflict markers present; manual resolution needed")

    return result


def write_summary(results: list[Result]) -> None:
    any_change = any(r.vendor_changed or r.derived_changed for r in results)
    any_conflict = any(r.derived_conflicts for r in results)
    any_skipped = any(r.skipped_reason for r in results)

    payload = {
        "any_change": any_change,
        "any_conflict": any_conflict,
        "any_skipped": any_skipped,
        "results": [
            {
                "name": r.name,
                "vendor_changed": r.vendor_changed,
                "derived_changed": r.derived_changed,
                "derived_conflicts": r.derived_conflicts,
                "skipped_reason": r.skipped_reason,
                "notes": r.notes,
            }
            for r in results
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    lines = ["# Upstream sync report", ""]
    for r in results:
        bits = []
        if r.vendor_changed:
            bits.append("vendor updated")
        if r.derived_changed:
            bits.append("derived updated")
        if r.derived_conflicts:
            bits.append("**conflicts**")
        if r.skipped_reason:
            bits.append(f"skipped: {r.skipped_reason}")
        if not bits:
            bits.append("no change")
        lines.append(f"- `{r.name}`: {', '.join(bits)}")
        for note in r.notes:
            lines.append(f"  - {note}")
    report = "\n".join(lines) + "\n"

    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as fp:
            fp.write(report)
    print(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Allow seeding new vendor files that do not exist yet.",
    )
    args = parser.parse_args()

    sources = load_sources(CONFIG_PATH)
    results = [sync_source(source, bootstrap=args.bootstrap) for source in sources]
    write_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
