#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Literal, Optional

import requests

BranchMode = Literal["rc", "final"]
Bump = Literal["none", "patch", "minor", "major"]

# ---------------- CONFIG ----------------
PACKAGES = ["aetherflow", "aetherflow-core", "aetherflow-scheduler"]
PACKAGES_DIR = "packages"

# breaking bumps MINOR (not major) per your preference
BREAKING_BUMPS: Bump = "minor"

# changes exist but no conventional commit signals
DEFAULT_BUMP_IF_CHANGES: Bump = "patch"

# tags like: <pkg>-v0.1.0 / <pkg>-v0.1.0rc1
TAG_PREFIX_FMT = "{pkg}-v"

ENV_RELEASE_PAT = "RELEASE_PAT"
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"
ENV_GITHUB_REPOSITORY = "GITHUB_REPOSITORY"
DEFAULT_REPO_SLUG = "aicodedao/aetherflow"
# --------------------------------------


# ---------------- logging helpers ----------------
def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"[INFO] {msg}", file=sys.stderr)


def _die(msg: str) -> None:
    raise RuntimeError(msg)


# ---------------- data models ----------------
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    rc: Optional[int] = None  # None => final

    @staticmethod
    def parse(s: str) -> "Version":
        m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?", s)
        if not m:
            raise ValueError(f"Unsupported version format: {s}")
        a, b, c, rc = m.groups()
        return Version(int(a), int(b), int(c), int(rc) if rc is not None else None)

    def __str__(self) -> str:
        if self.rc is None:
            return f"{self.major}.{self.minor}.{self.patch}"
        return f"{self.major}.{self.minor}.{self.patch}rc{self.rc}"

    def base(self) -> "Version":
        return Version(self.major, self.minor, self.patch, None)

    def bump(self, kind: Bump) -> "Version":
        if kind == "none":
            return self
        if kind == "patch":
            return Version(self.major, self.minor, self.patch + 1, None)
        if kind == "minor":
            return Version(self.major, self.minor + 1, 0, None)
        if kind == "major":
            return Version(self.major + 1, 0, 0, None)
        raise ValueError(kind)

    def to_rc(self, n: int) -> "Version":
        return Version(self.major, self.minor, self.patch, n)


@dataclass
class CommitEntry:
    sha: str
    subject: str
    body: str
    typ: str
    scope: Optional[str]
    breaking: bool


@dataclass
class ReleasePlan:
    pkg: str
    pkg_dir: Path
    pyproject: Path
    last_tag: Optional[str]
    last_version: Version
    mode: BranchMode
    bump: Bump
    next_version: Version
    commits: list[CommitEntry]
    changed_files: list[str]


# ---------------- git helpers ----------------
def _run_dbg(cmd: Iterable[str], *, cwd: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = list(cmd)
    print("\n$ " + " ".join(shlex.quote(x) for x in cmd), file=sys.stderr)
    p = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"[exit={p.returncode}]", file=sys.stderr)
    if p.stdout:
        print("\n--- stdout ---", file=sys.stderr)
        print(p.stdout.rstrip(), file=sys.stderr)
    if p.stderr:
        print("\n--- stderr ---", file=sys.stderr)
        print(p.stderr.rstrip(), file=sys.stderr)
    return p


def _run(
        cmd: list[str],
        cwd: str | Path | None = None,
        *,
        check: bool = True,
        **kwargs,
) -> str:
    """
    Run a command with consistent logging.

    If caller passes stdout/stderr, we do NOT use capture_output.
    Otherwise, capture stdout/stderr so we can print in --debug and include in errors.
    """

    text = kwargs.pop("text", True)

    has_stdout = "stdout" in kwargs and kwargs["stdout"] is not None
    has_stderr = "stderr" in kwargs and kwargs["stderr"] is not None

    run_kwargs = {
        "text": text,
        "cwd": str(cwd) if cwd else None,
        **kwargs,
    }

    if not has_stdout and not has_stderr:
        run_kwargs["capture_output"] = True

    p = subprocess.run(cmd, **run_kwargs)

    if check and p.returncode != 0:
        raise subprocess.CalledProcessError(
            p.returncode,
            p.args,
            output=getattr(p, "stdout", None),
            stderr=getattr(p, "stderr", None),
        )

    return p.stdout.strip()


def _repo_root() -> Path:
    return Path(_run(["git", "rev-parse", "--show-toplevel"])).resolve()


def _ensure_clean(*, allow_dirty: bool) -> None:
    st = _run(["git", "status", "--porcelain"], check=True)
    if st.strip() and not allow_dirty:
        _die(f"Working tree dirty. Commit/stash first.\n{st}")


def _head_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"])


def _current_branch() -> str:
    # In Actions checkout can be detached. Treat as WARNING; we should not hard-fail.
    b = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return b


def _fetch_all() -> None:
    _run(["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"], check=True)
    _run(["git", "fetch", "--tags", "origin"], check=True)


def _ensure_remote_branch_exists(branch: str) -> None:
    _fetch_all()
    out = _run(["git", "ls-remote", "--heads", "origin", branch], check=True)
    if not out.strip():
        _die(f"Remote branch origin/{branch} not found.")


def _origin_sha(branch: str) -> str:
    _ensure_remote_branch_exists(branch)
    return _run(["git", "rev-parse", f"origin/{branch}"], check=True)


def _ensure_head_matches_origin(branch: str) -> None:
    """
    Critical: base branch HEAD must match origin/<branch>.
    This prevents releasing from stale local state.
    """
    _fetch_all()
    local = _head_sha()
    remote = _origin_sha(branch)
    if local != remote:
        _die(
            f"Base branch mismatch:\n"
            f"- local HEAD:  {local}\n"
            f"- origin/{branch}: {remote}\n"
            f"Checkout the branch from origin and retry."
        )


def _checkout_branch(branch: str) -> None:
    _run(["git", "checkout", branch], check=True)


def _is_merge_commit(sha: str) -> bool:
    p = _run(["git", "rev-list", "--parents", "-n", "1", sha], check=True)
    parts = (p or "").strip().split()
    # format: <sha> <parent1> <parent2> ...
    return len(parts) > 2

def _second_parent(sha: str) -> str:
    p = _run(["git", "rev-parse", f"{sha}^2"], check=True)
    return (p or "").strip()

def _checkout_release_branch(release_branch: str, *, base_sha: str) -> None:
    """
    Create/update release branch to point at base_sha and check it out.

    - If branch exists locally: reset it to base_sha.
    - If not: create it at base_sha.
    """
    if _is_merge_commit(base_sha):
        _info(f"Base SHA {base_sha} is a merge commit; using second parent to satisfy repo rules.")
        base_sha = _second_parent(base_sha)
    # does local branch exist?
    p = subprocess.run(["git", "show-ref", "--verify", f"refs/heads/{release_branch}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if p.returncode == 0:
        _run(["git", "checkout", release_branch], check=True)
        _run(["git", "merge", "--ff-only", base_sha], check=True)
        return
    _run(["git", "checkout", "-b", release_branch, base_sha], check=True)


def _push_release_branch(release_branch: str) -> None:
    """
    Push release branch. If it already exists remotely, overwrite it only if fast-forward.
    """
    # -u is fine even if exists; git handles it. If branch protection blocks it, that's a hard fail.
    _run(["git", "push", "-u", "origin", release_branch, "--force-with-lease", "--verbose"], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _push_tag(tag: str) -> None:
    # idempotent-ish: push only if not on remote
    out = _run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"], check=True)
    if out.strip():
        _info(f"Remote tag already exists, skipping: {tag}")
        return
    _run(["git", "tag", tag], check=True)
    _run(["git", "push", "origin", tag], check=True)


def _git_commit_all(message: str) -> None:
    _run(["git", "add", "-A"], check=True)
    names = _run(["git", "diff", "--cached", "--name-only"], check=True)
    if names.strip():
        _run(["git", "commit", "-m", message], check=True)


def _list_tags() -> list[str]:
    out = _run(["git", "tag", "--list"], check=True)
    return [t for t in out.splitlines() if t.strip()]


# ---------------- conventional commit parsing ----------------
_CONV_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s+(?P<desc>.+)$")


def _parse_conventional_commit(*, sha: str, subject: str, body: str) -> CommitEntry:
    m = _CONV_RE.match(subject)
    if m:
        typ = m.group("type").lower()
        scope = m.group("scope")
        bang = m.group("bang") == "!"
        breaking = bang or ("BREAKING CHANGE" in body)
        return CommitEntry(sha=sha, subject=subject, body=body, typ=typ, scope=scope, breaking=breaking)

    return CommitEntry(
        sha=sha,
        subject=subject,
        body=body,
        typ="other",
        scope=None,
        breaking=("BREAKING CHANGE" in body),
    )


def _git_log_commits_since(tag: Optional[str], path_prefix: str) -> list[CommitEntry]:
    fmt = "%H%n%s%n%b%n==END=="
    if tag:
        out = _run(["git", "log", f"{tag}..HEAD", "--pretty=format:" + fmt, "--", path_prefix], check=True)
    else:
        out = _run(["git", "log", "--pretty=format:" + fmt, "--", path_prefix], check=True)

    blocks = out.split("==END==")
    commits: list[CommitEntry] = []
    for b in blocks:
        b = b.strip("\n")
        if not b.strip():
            continue
        lines = b.splitlines()
        sha = lines[0].strip() if lines else ""
        subject = lines[1].strip() if len(lines) > 1 else ""
        body = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        commits.append(_parse_conventional_commit(sha=sha, subject=subject, body=body))

    commits.reverse()
    return commits


def _max_bump(a: Bump, b: Bump) -> Bump:
    order = {"none": 0, "patch": 1, "minor": 2, "major": 3}
    inv = {v: k for k, v in order.items()}
    return inv[max(order[a], order[b])]


def _bump_from_commits(commits: list[CommitEntry], has_changes: bool) -> Bump:
    if not has_changes:
        return "none"

    bump: Bump = "none"
    for c in commits:
        if c.breaking:
            bump = _max_bump(bump, BREAKING_BUMPS)
        elif c.typ == "feat":
            bump = _max_bump(bump, "minor")
        elif c.typ in ("fix", "perf"):
            bump = _max_bump(bump, "patch")

    if bump == "none":
        bump = DEFAULT_BUMP_IF_CHANGES
    return bump


def _next_version_for_mode(last: Version, bump: Bump, mode: BranchMode) -> Version:
    base = last.base()
    bumped = base.bump(bump)

    if mode == "final":
        return bumped

    # rc mode: if last tag was rc for same bumped base -> rc+1 else rc1
    if last.rc is not None and (last.major, last.minor, last.patch) == (bumped.major, bumped.minor, bumped.patch):
        return bumped.to_rc(last.rc + 1)
    return bumped.to_rc(1)


# ---------------- tag/version helpers ----------------
def _tag_name(pkg: str, version: Version) -> str:
    return f"{TAG_PREFIX_FMT.format(pkg=pkg)}{version}"


def _extract_version_from_tag(pkg: str, tag: str) -> Optional[Version]:
    prefix = TAG_PREFIX_FMT.format(pkg=pkg)
    if not tag.startswith(prefix):
        return None
    v = tag[len(prefix) :]
    try:
        return Version.parse(v)
    except Exception:
        return None


def _latest_pkg_tag(pkg: str) -> tuple[Optional[str], Version]:
    tags = _list_tags()
    best_tag = None
    best_ver: Optional[Version] = None

    for t in tags:
        v = _extract_version_from_tag(pkg, t)
        if v is None:
            continue
        if best_ver is None:
            best_ver, best_tag = v, t
            continue

        a = (v.major, v.minor, v.patch)
        b = (best_ver.major, best_ver.minor, best_ver.patch)
        if a != b:
            if a > b:
                best_ver, best_tag = v, t
            continue

        # same base
        if best_ver.rc is None:
            continue
        if v.rc is None:
            best_ver, best_tag = v, t
            continue
        if v.rc > best_ver.rc:
            best_ver, best_tag = v, t

    if best_ver is None:
        return None, Version(0, 0, 0, None)
    return best_tag, best_ver


def _first_commit() -> str:
    out = _run(["git", "rev-list", "--max-parents=0", "HEAD"], check=True)
    commits = [x.strip() for x in out.splitlines() if x.strip()]
    if not commits:
        _die("Cannot determine first commit (repo has no commits?)")
    return commits[-1]


def _changed_files_since(tag: Optional[str], path_prefix: str) -> list[str]:
    if tag:
        out = _run(["git", "diff", "--name-only", f"{tag}..HEAD", "--", path_prefix], check=True)
    else:
        base = _first_commit()
        out = _run(["git", "diff", "--name-only", f"{base}..HEAD", "--", path_prefix], check=True)
    return [x for x in out.splitlines() if x.strip()]


# ---------------- pyproject editing ----------------
def _write_pyproject_version(pyproject: Path, new_version: Version) -> None:
    text = pyproject.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'(^\s*version\s*=\s*")([^"]+)(")',
        rf"\g<1>{new_version}\g<3>",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        _die(f"Could not update version in {pyproject} (expected exactly 1 match)")
    pyproject.write_text(new_text, encoding="utf-8")


# ---------------- changelog ----------------
def _changelog_path(pkg_dir: Path) -> Path:
    return pkg_dir / "CHANGELOG.md"


def _ensure_changelog_scaffold(pkg_dir: Path) -> None:
    ch = _changelog_path(pkg_dir)
    if ch.exists():
        return
    ch.write_text(
        "# Changelog\n\n"
        "All notable changes to this project will be documented in this file.\n\n"
        "The format is based on Keep a Changelog.\n"
        "This project follows semantic versioning.\n\n"
        "## [Unreleased]\n\n",
        encoding="utf-8",
    )


def _render_release_entry(plan: ReleasePlan, repo_slug: str, new_tag: str, prev_tag: Optional[str]) -> str:
    title = f"## [{plan.next_version}] - {date.today().isoformat()}"
    groups: dict[str, list[CommitEntry]] = {}

    for c in plan.commits:
        groups.setdefault(c.typ, []).append(c)

    def bullet(c: CommitEntry) -> str:
        scope = f"**{c.scope}**: " if c.scope else ""
        breaking = " **(BREAKING)**" if c.breaking else ""
        short = c.sha[:7]
        return f"- {scope}{c.subject}{breaking} ({short})"

    sections: list[str] = []
    mapping = [
        ("feat", "Added"),
        ("fix", "Fixed"),
        ("perf", "Performance"),
        ("refactor", "Changed"),
        ("docs", "Documentation"),
        ("test", "Tests"),
        ("ci", "CI"),
        ("build", "Build"),
        ("chore", "Chore"),
        ("other", "Other"),
    ]
    for typ, label in mapping:
        items = groups.get(typ, [])
        if not items:
            continue
        sections.append(f"### {label}\n")
        sections.extend(bullet(c) for c in items)
        sections.append("")

    body = "\n".join([title, ""] + sections).rstrip() + "\n"

    if prev_tag:
        compare = f"https://github.com/{repo_slug}/compare/{prev_tag}...{new_tag}"
        body += f"\nCompare: {compare}\n"
    return body.strip() + "\n"


def _insert_release_entry_under_unreleased(pkg_dir: Path, entry: str) -> None:
    _ensure_changelog_scaffold(pkg_dir)
    ch = _changelog_path(pkg_dir)
    text = ch.read_text(encoding="utf-8")

    if "## [Unreleased]" not in text:
        text = text.replace("# Changelog\n\n", "# Changelog\n\n## [Unreleased]\n\n", 1)

    marker = "## [Unreleased]\n\n"
    if marker not in text:
        marker = "## [Unreleased]\n"
        if marker not in text:
            _die(f"CHANGELOG.md missing [Unreleased] section in {pkg_dir}")

    if marker == "## [Unreleased]\n\n":
        new_text = text.replace(marker, marker + entry + "\n", 1)
    else:
        new_text = text.replace(marker, marker + "\n" + entry + "\n", 1)

    ch.write_text(new_text, encoding="utf-8")


def _append_link_definition(pkg_dir: Path, version: Version, repo_slug: str, prev_tag: Optional[str], new_tag: str) -> None:
    if not prev_tag:
        return
    ch = _changelog_path(pkg_dir)
    text = ch.read_text(encoding="utf-8").rstrip() + "\n"
    link_line = f"[{version}]: https://github.com/{repo_slug}/compare/{prev_tag}...{new_tag}\n"
    if link_line in text:
        return
    ch.write_text(text + "\n" + link_line, encoding="utf-8")


# ---------------- GitHub API (optional: release notes) ----------------
def _detect_repo_slug() -> str:
    url = _run(["git", "remote", "get-url", "origin"], check=True)
    if url.startswith("git@"):
        slug = url.split(":", 1)[1]
    elif url.startswith(("https://", "http://")):
        path = urllib.parse.urlparse(url).path
        slug = path.lstrip("/")
    else:
        _die(f"Unsupported origin URL: {url}")
    return slug.removesuffix(".git")


def _require_token() -> str:
    # Prefer PAT so GitHub Release shows real actor (and avoids bot-only behavior)
    pat = os.getenv(ENV_RELEASE_PAT)
    if pat:
        return pat

    tok = os.getenv(ENV_GITHUB_TOKEN)
    if tok:
        return tok

    _die(f"{ENV_RELEASE_PAT} or {ENV_GITHUB_TOKEN} is required.")
    raise RuntimeError("unreachable")


def _maybe_auth_origin_with_pat() -> None:
    pat = os.getenv(ENV_RELEASE_PAT)
    if not pat:
        return
    repo = os.getenv(ENV_GITHUB_REPOSITORY) or DEFAULT_REPO_SLUG
    url = f"https://x-access-token:{pat}@github.com/{repo}.git"
    _run(["git", "remote", "set-url", "origin", url], check=True)
    _info("origin now: " + _run(["git", "remote", "get-url", "origin"], check=True))


def _github_headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def _github_api_base(repo_slug: str) -> str:
    owner, repo = repo_slug.split("/", 1)
    return f"https://api.github.com/repos/{owner}/{repo}"


def _create_github_release(repo_slug: str, tag: str, name: str, body: str, token: str, prerelease: bool) -> None:
    url = _github_api_base(repo_slug) + "/releases"
    payload = {
        "tag_name": tag,
        "name": name,
        "body": body,
        "draft": False,
        "prerelease": prerelease,
    }
    r = requests.post(url, headers=_github_headers(token), json=payload, timeout=30)
    if r.status_code in (200, 201):
        return
    # Not critical to publishing; warn only.
    _warn(f"Failed to create GitHub Release for {tag}: {r.status_code} {r.text}")


# ---------------- planning ----------------
def build_plan_for_pkg(pkg: str, mode: BranchMode) -> ReleasePlan:
    root = _repo_root()
    pkg_dir = root / PACKAGES_DIR / pkg
    pyproject = pkg_dir / "pyproject.toml"
    if not pyproject.exists():
        _die(f"Missing {pyproject}")

    last_tag, last_ver = _latest_pkg_tag(pkg)
    changed = _changed_files_since(last_tag, f"{PACKAGES_DIR}/{pkg}")
    commits = _git_log_commits_since(last_tag, f"{PACKAGES_DIR}/{pkg}")
    bump = _bump_from_commits(commits, has_changes=bool(changed))
    next_ver = _next_version_for_mode(last_ver, bump, mode)

    return ReleasePlan(
        pkg=pkg,
        pkg_dir=pkg_dir,
        pyproject=pyproject,
        last_tag=last_tag,
        last_version=last_ver,
        mode=mode,
        bump=bump,
        next_version=next_ver,
        commits=commits,
        changed_files=changed,
    )


def _apply_plan_on_release_branch(plan: ReleasePlan, repo_slug: str) -> tuple[Optional[str], str]:
    """
    Assumes we are already on release branch.
    Performs:
      - bump pyproject version
      - update changelog
      - commit
    Returns: (tag, changelog_entry)
    """
    if plan.bump == "none":
        return None, ""

    prev_tag = plan.last_tag
    new_tag = _tag_name(plan.pkg, plan.next_version)
    entry = _render_release_entry(plan, repo_slug, new_tag, prev_tag)

    _write_pyproject_version(plan.pyproject, plan.next_version)
    _insert_release_entry_under_unreleased(plan.pkg_dir, entry)
    _append_link_definition(plan.pkg_dir, plan.next_version, repo_slug, prev_tag, new_tag)

    _git_commit_all(f"release({plan.pkg}): {plan.next_version}")

    return new_tag, entry


def main() -> int:
    ap = argparse.ArgumentParser("Monorepo release tool (branch-based; no PR API).")

    ap.add_argument("--mode", choices=["rc", "final"], required=True)
    ap.add_argument("--packages", nargs="*", default=PACKAGES)

    ap.add_argument("--base-branch", required=True, help="Base branch to release from (e.g. test / master)")
    ap.add_argument("--release-branch", required=True, help="Branch to push release commits to (e.g. release-test / release)")

    ap.add_argument("--push", action="store_true", help="Push release branch + tags to origin")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--force-bump", choices=["patch", "minor", "major"], default="patch")
    ap.add_argument("--allow-dirty", action="store_true")

    ap.add_argument("--skip-base-sync-check", action="store_true", help="WARNING: allows releasing even if local != origin/base")
    ap.add_argument("--skip-github-release", action="store_true", help="Don't create GitHub Releases via API")

    ap.add_argument("--debug", action="store_true")

    args = ap.parse_args()

    mode: BranchMode = args.mode  # type: ignore
    base_branch: str = args.base_branch
    release_branch: str = args.release_branch

    # --- preflight ---
    if args.debug:
        _run_dbg(["git", "--version"])
        _run_dbg(["git", "status", "--porcelain=v1", "-b"])
        _run_dbg(["git", "remote", "-v"])
        _run_dbg(["git", "rev-parse", "HEAD"])

    _ensure_clean(allow_dirty=args.allow_dirty)

    # HEAD branch in Actions can be detached => WARNING only
    cur = _current_branch()
    if cur == "HEAD":
        _warn("Detached HEAD detected (common in GitHub Actions). Continuing.")
    else:
        _info(f"Current branch: {cur}")

    # Ensure base branch exists on remote
    _ensure_remote_branch_exists(base_branch)

    # Checkout base branch to base SHA, and ensure local matches origin/base unless skipped
    _checkout_branch(base_branch)
    _fetch_all()
    _run(["git", "reset", "--hard", f"origin/{base_branch}"], check=True)
    base_sha = _head_sha()

    if not args.skip_base_sync_check:
        _ensure_head_matches_origin(base_branch)
    else:
        _warn("skip-base-sync-check enabled: not enforcing local HEAD == origin/base.")

    repo_slug = os.getenv(ENV_GITHUB_REPOSITORY) or DEFAULT_REPO_SLUG or _detect_repo_slug()

    # Build plans (on base)
    plans = [build_plan_for_pkg(p, mode) for p in args.packages]

    if args.force:
        for pl in plans:
            if pl.bump == "none":
                pl.bump = args.force_bump  # type: ignore
                pl.next_version = _next_version_for_mode(pl.last_version, pl.bump, mode)
    else:
        plans = [p for p in plans if p.bump != "none"]

    if not plans:
        _info("No package changes detected since last tags. Nothing to release.")
        return 0

    print("\n=== RELEASE PLAN ===")
    for p in plans:
        print(f"\n[{p.pkg}]")
        print(f"  last_tag      : {p.last_tag or '(none)'}")
        print(f"  last_version  : {p.last_version}")
        print(f"  bump          : {p.bump}")
        print(f"  next_version  : {p.next_version}   ({p.mode})")
        print(f"  commits       : {len(p.commits)}")
        print(f"  files changed : {len(p.changed_files)}")

    if args.dry_run:
        print("\nDRY-RUN: no files changed, no commits/tags created.\n")
        return 0

    # Switch to release branch anchored at base SHA (critical!)
    _checkout_release_branch(release_branch, base_sha=base_sha)

    # Apply plans on release branch
    tags: list[str] = []
    entries_by_tag: dict[str, str] = {}

    for p in plans:
        t, entry = _apply_plan_on_release_branch(p, repo_slug=repo_slug)
        if t:
            tags.append(t)
            entries_by_tag[t] = entry

    if not tags:
        _info("No releases produced (unexpected).")
        return 0

    # Push branch + tags
    if args.push:
        _maybe_auth_origin_with_pat()
        _push_release_branch(release_branch)

        for t in tags:
            _push_tag(t)

        # GitHub Releases are optional: failures are warnings
        if not args.skip_github_release:
            token = _require_token()
            prerelease = (mode == "rc")
            for t in tags:
                body = entries_by_tag.get(t, "").strip()
                _create_github_release(
                    repo_slug=repo_slug,
                    tag=t,
                    name=t,
                    body=body + ("\n" if body else ""),
                    token=token,
                    prerelease=prerelease,
                )
        else:
            _warn("skip-github-release enabled: not creating GitHub Releases via API.")

        print("\n✅ Released tags:")
        for t in tags:
            print(" -", t)
    else:
        print("\n✅ Local release branch commits created (no push). Planned tags:")
        for t in tags:
            print(" -", t)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
