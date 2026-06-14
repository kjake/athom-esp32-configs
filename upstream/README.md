# Vendored upstream files

The files under this directory are **pristine** mirrors of upstream sources.
Do not edit them by hand — they are refreshed automatically by
`.github/workflows/upstream-sync.yml` (which runs `scripts/sync-upstream.py`).

Customizations belong in `common/` and at the repo root.

The mapping of upstream URLs to vendor paths lives in
`.github/upstream-sources.yaml`.

## How the sync works

For each tracked source:

1. The script fetches the upstream URL.
2. The new bytes replace the vendored copy.
3. If the source declares a `derived:` path, a git-style 3-way merge runs
   with the previous vendored copy as the base, the new upstream as
   theirs, and the current derived file as ours.
4. The merged result replaces the derived file. Conflict markers are left
   in place when the merge can't auto-resolve, and the workflow opens the
   sync PR as a draft so a human can resolve them.

## Adding a new source

1. Add an entry under `sources:` in `.github/upstream-sources.yaml`.
2. Run the `Upstream Sync` workflow manually with `bootstrap: true` to seed
   the vendor file, or locally: `python3 scripts/sync-upstream.py --bootstrap`.
3. Commit the resulting vendor file.
