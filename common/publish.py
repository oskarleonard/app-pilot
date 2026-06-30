#!/usr/bin/env python3
"""Publish a QA image to the hidden app-pilot-assets store; print a PR-ready <img>.

WHY: QA before/after montages must NOT be committed to the feature/PR branch —
on squash-merge that lands them in `main`. They also shouldn't live on a
regular branch: GitHub shows a "had recent pushes — Compare & pull request"
banner for any freshly-pushed branch, every single run. So images live on a
**custom ref** outside the branch namespace:

    refs/app-pilot-assets/store

No branch → no banner, no branch-list entry, nothing to merge or PR. The ref's
history is append-only and shares no ancestry with `main`. PR bodies reference
images by COMMIT-PINNED raw URL, which never rots:

    https://github.com/<owner>/<repo>/blob/<commit-sha>/<path>?raw=true

These URLs render inline in a PR for any viewer authenticated to the repo —
even a PRIVATE repo, even though the commit is on a hidden (non-branch) ref.
Do NOT judge a published URL with an anonymous `curl`: a private repo returns
404 to unauthenticated requests for EVERY ref, so a curl 404 is a false
negative, not a broken link. Verify authenticated instead:
    gh api repos/<owner>/<repo>/contents/<path>?ref=<ref> -H "Accept: application/vnd.github.raw" | wc -c

Migration: repos that previously used the `app-pilot-assets` BRANCH get seamless
continuity — the first publish seeds the store ref from the legacy branch tip,
so the old branch can stay frozen (its embedded URLs keep working) while all
new publishes go to the hidden ref.

Everything happens via an ISOLATED temp index (never touches your working
tree, current branch, or HEAD). Idempotent: re-publishing identical content
reuses the existing commit. `<owner>/<repo>` derives from `origin`, so the
same command works in any repo.

Usage:
  app-pilot publish <image> --feature <slug> [--name <file>] [--caption <text>] [--width N]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

REF = "refs/app-pilot-assets/store"
# One-time seed chain so every already-published commit-pinned PR image URL
# stays reachable across the qa→app-pilot rename: new ref → the prior
# qa-assets store ref → the original qa-assets branch. Old refs are never
# auto-deleted, so old URLs keep resolving regardless.
_PRIOR_REF = "refs/qa-assets/store"
_LEGACY_BRANCH = "qa-assets"

_README = """\
# app-pilot-assets — image store for QA artifacts

Machine-managed, append-only store of images referenced from PR descriptions
(automated QA before/after montages, etc.).

- Lives on the hidden ref `refs/app-pilot-assets/store` — NOT a branch: no UI
  banners, no branch-list entry, nothing to merge or PR.
- Shares no history with `main`; never reachable from any branch.
- PR bodies link images by commit-pinned raw URL, so links never rot.

Managed by the QA tester's `app-pilot publish` command. Do not delete the ref
(PR bodies link into its history).
"""


def git(*args, env=None, check=True):
    r = subprocess.run(["git", *args], text=True, capture_output=True, env=env)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def owner_repo():
    """Parse 'owner/repo' from the origin remote (https or ssh form)."""
    url = git("remote", "get-url", "origin")
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"cannot parse owner/repo from origin remote: {url!r}")
    return m.group(1)


def remote_base():
    """Tip to build the next commit on. Seeds in order: the app-pilot-assets
    store ref → the prior qa-assets store ref → the original qa-assets branch —
    so history stays continuous and every already-published commit-pinned URL
    stays reachable after the rename. None only on a truly fresh repo."""
    for ref in (REF, _PRIOR_REF):
        git("fetch", "origin", f"+{ref}:{ref}", check=False)  # fine if absent
        tip = git("rev-parse", "--verify", "--quiet", ref, check=False)
        if tip:
            return tip
    git("fetch", "origin", _LEGACY_BRANCH, check=False)
    return git("rev-parse", "--verify", "--quiet",
               f"refs/remotes/origin/{_LEGACY_BRANCH}", check=False) or None


def hash_blob(path):
    return git("hash-object", "-w", path)


def build_tree(base, env, dest, image):
    """Tree = base tree (if any) + image at <dest> (+ a README when bootstrapping)."""
    if base:
        git("read-tree", base, env=env)
    else:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        tmp.write(_README)
        tmp.close()
        git("update-index", "--add", "--cacheinfo",
            f"100644,{hash_blob(tmp.name)},README.md", env=env)
        os.unlink(tmp.name)
    git("update-index", "--add", "--cacheinfo",
        f"100644,{hash_blob(image)},{dest}", env=env)
    return git("write-tree", env=env)


def emit_snippet(url, caption, width):
    print("\n--- paste into the PR body ---")
    if caption:
        print(f"**{caption}**")
    print(f'<img src="{url}" width="{width}" alt="{caption or "QA before/after"}" />')


def main():
    ap = argparse.ArgumentParser(
        prog="app-pilot publish",
        description="Host a QA image on the hidden app-pilot-assets store ref (keeps it out of main, branches, and banners).",
    )
    ap.add_argument("image", help="path to the image (montage/screenshot) to host")
    ap.add_argument("--feature", required=True,
                    help="folder slug in the store, e.g. transfer-account-name-capitalize")
    ap.add_argument("--name", help="filename in the store (default: image basename); "
                    "an image extension is auto-added if omitted, so the URL renders inline")
    ap.add_argument("--caption", default="", help="caption / alt text for the <img>")
    ap.add_argument("--width", type=int, default=580,
                    help="display width in the PR body (default 580 — the standard)")
    a = ap.parse_args()

    if not os.path.isfile(a.image):
        sys.exit(f"image not found: {a.image}")
    os.chdir(git("rev-parse", "--show-toplevel"))

    # The store filename must carry an image extension — GitHub serves an
    # extensionless blob as octet-stream, so an <img src=…> at it renders
    # broken. --name is a filename, not a path, so take its basename; if it
    # has no extension borrow the source image's, and if even that yields none
    # (extensionless source) fail loud rather than publish a silently-broken URL.
    name = os.path.basename(a.name or a.image)
    if not os.path.splitext(name)[1]:
        name += os.path.splitext(a.image)[1]
    if not os.path.splitext(name)[1]:
        sys.exit(f"cannot derive an image extension for {name!r} — give --name a "
                 "name ending in an image extension, or publish a source file that has one")
    dest = f"{a.feature.strip('/')}/{name}"
    base = remote_base()

    idx = tempfile.mktemp(suffix=".idx")  # isolated index → never touches the real one
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    tree = build_tree(base, env, dest, a.image)
    if os.path.exists(idx):
        os.unlink(idx)

    if base and tree == git("rev-parse", f"{base}^{{tree}}"):
        commit = base
        print(f"already published (identical content) — commit {commit[:9]}")
    else:
        msg = f"app-pilot-assets: {dest}"
        commit = git("commit-tree", tree, "-p", base, "-m", msg) if base \
            else git("commit-tree", tree, "-m", msg)
        push = subprocess.run(["git", "push", "origin", f"{commit}:{REF}"],
                              text=True, capture_output=True)
        if push.returncode != 0:
            sys.exit("push to the app-pilot-assets store failed (someone else may have "
                     f"published — re-run to retry):\n{push.stderr.strip()}")
        git("update-ref", REF, commit)  # keep the local store ref in sync
        print(f"published -> commit {commit[:9]} on {REF}")

    url = f"https://github.com/{owner_repo()}/blob/{commit}/{dest}?raw=true"
    emit_snippet(url, a.caption, a.width)


if __name__ == "__main__":
    main()
