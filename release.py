#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import requests

BranchMode = Literal["rc", "final"]
Bump = Literal["none", "patch", "minor", "major"]

# ---------------- CONFIG ----------------
PACKAGES = ["aetherflow", "aetherflow-core", "aetherflow-scheduler"]
PACKAGES_DIR = "packages"

# per your request: breaking bumps MINOR (not major). Change to "major" if you want true semver.
BREAKING_BUMPS: Bump = "minor"

# when there are changes but no conventional commit signals
DEFAULT_BUMP_IF_CHANGES: Bump = "patch"

# tags like: <pkg>-v0.1.0 / <pkg>-v0.1.0rc1
TAG_PREFIX_FMT = "{pkg}-v"

# required branches for each mode
REQUIRED_BRANCH_FOR_MODE = {"rc": "test", "final": "master"}

# Environment variable NAMES the script will read from
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"
ENV_GITHUB_REPOSITORY = "GITHUB_REPOSITORY"  # usually "owner/repo" in Actions
# Optional static fallback (useful for local dev if you want a default)
DEFAULT_REPO_SLUG = "aicodedao/aetherflow" # if you insist on a fallback
# --------------------------------------


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
    typ: str   # feat/fix/perf/docs/refactor/chore/ci/build/test/other
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


# ---------------- Git helpers ----------------

def _run(cmd: list[str], cwd: str | Path | None = None) -> str:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return p.stdout.strip()


def _repo_root() -> Path:
    return Path(_run(["git", "rev-parse", "--show-toplevel"])).resolve()


def _ensure_clean() -> None:
    st = _run(["git", "status", "--porcelain"])
    if st.strip():
        raise RuntimeError(f"Working tree dirty. Commit/stash first.\n{st}")


def _current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _head_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"])


def _fetch_all() -> None:
    _run(["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"])
    _run(["git", "fetch", "--tags", "origin"])


def _remote_branches_containing(commit: str) -> list[str]:
    out = _run(["git", "branch", "-r", "--contains", commit])
    return [x.strip() for x in out.splitlines() if x.strip()]


def _ensure_commit_on_branch(commit: str, branch: str) -> None:
    """
    Enforce "origin/<branch> contains commit" like workflow.
    """
    _fetch_all()
    branches = _remote_branches_containing(commit)
    target = f"origin/{branch}"
    if target not in branches:
        msg = "\n".join(branches) if branches else "(none)"
        raise RuntimeError(
            f"Commit {commit} is NOT contained in {target}. Aborting.\n"
            f"Remote branches containing commit:\n{msg}"
        )


def _list_tags() -> list[str]:
    out = _run(["git", "tag", "--list"])
    return [t for t in out.splitlines() if t.strip()]


def _tag_name(pkg: str, version: Version) -> str:
    return f"{TAG_PREFIX_FMT.format(pkg=pkg)}{version}"


def _extract_version_from_tag(pkg: str, tag: str) -> Optional[Version]:
    prefix = TAG_PREFIX_FMT.format(pkg=pkg)
    if not tag.startswith(prefix):
        return None
    v = tag[len(prefix):]
    try:
        return Version.parse(v)
    except Exception:
        return None


def _latest_pkg_tag(pkg: str) -> tuple[Optional[str], Version]:
    """
    Determine latest tag for a package using semantic ordering:
    - higher base version wins
    - for same base, final > rc; else higher rc wins
    If no tags, baseline version is 0.0.0.
    """
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


def _rev_range_since(tag: Optional[str]) -> str:
    return f"{tag}..HEAD" if tag else "HEAD"


def _changed_files_since(tag: Optional[str], path_prefix: str) -> list[str]:
    rr = _rev_range_since(tag)
    out = _run(["git", "diff", "--name-only", rr, "--", path_prefix])
    return [x for x in out.splitlines() if x.strip()]


# ---------------- Conventional commit parsing ----------------

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
    """
    commits affecting a given path since last tag, oldest-first.
    """
    rr = _rev_range_since(tag)
    fmt = "%H%n%s%n%b%n==END=="
    out = _run(["git", "log", rr, "--pretty=format:" + fmt, "--", path_prefix])
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
    # bump base from last final base (if last is rc -> its base)
    base = last.base()
    bumped = base.bump(bump)

    if mode == "final":
        return bumped

    # rc mode: if last tag was rc for same bumped base -> rc+1 else rc1
    if last.rc is not None and (last.major, last.minor, last.patch) == (bumped.major, bumped.minor, bumped.patch):
        return bumped.to_rc(last.rc + 1)
    return bumped.to_rc(1)


# ---------------- pyproject editing ----------------

def _read_pyproject_version(pyproject: Path) -> Version:
    import tomllib
    d = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    v = d.get("project", {}).get("version") or d.get("tool", {}).get("poetry", {}).get("version")
    if not v:
        raise RuntimeError(f"Cannot find version in {pyproject}")
    return Version.parse(str(v).strip())


def _write_pyproject_version(pyproject: Path, new_version: Version) -> None:
    text = pyproject.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'(^\s*version\s*=\s*")([^"]+)(")',
        rf'\g<1>{new_version}\g<3>',
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise RuntimeError(f"Could not update version in {pyproject} (expected exactly 1 match)")
    pyproject.write_text(new_text, encoding="utf-8")


# ---------------- Keep a Changelog ----------------

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
    """
    Build a Keep-a-Changelog style entry for a specific version.
    """
    title = f"## [{plan.next_version}] - {date.today().isoformat()}"
    groups: dict[str, list[CommitEntry]] = {}

    for c in plan.commits:
        groups.setdefault(c.typ, []).append(c)

    def bullet(c: CommitEntry) -> str:
        scope = f"**{c.scope}**: " if c.scope else ""
        breaking = " **(BREAKING)**" if c.breaking else ""
        short = c.sha[:7]
        # Use subject as-is; it already includes type(scope): desc
        return f"- {scope}{c.subject}{breaking} ({short})"

    sections = []
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

    # Compare link (also stored in links section at bottom)
    if prev_tag:
        compare = f"https://github.com/{repo_slug}/compare/{prev_tag}...{new_tag}"
        body += f"\nCompare: {compare}\n"
    return body.strip() + "\n"


def _insert_release_entry_under_unreleased(pkg_dir: Path, entry: str) -> None:
    """
    Put entry immediately after '## [Unreleased]'.
    """
    _ensure_changelog_scaffold(pkg_dir)
    ch = _changelog_path(pkg_dir)
    text = ch.read_text(encoding="utf-8")

    if "## [Unreleased]" not in text:
        # If user has custom changelog, force inject Unreleased after title.
        text = text.replace("# Changelog\n\n", "# Changelog\n\n## [Unreleased]\n\n", 1)

    marker = "## [Unreleased]\n\n"
    if marker not in text:
        # Accept variant "## [Unreleased]\n"
        marker = "## [Unreleased]\n"
        if marker not in text:
            raise RuntimeError(f"CHANGELOG.md missing [Unreleased] section in {pkg_dir}")

    # insert entry once
    if marker == "## [Unreleased]\n\n":
        new_text = text.replace(marker, marker + entry + "\n", 1)
    else:
        new_text = text.replace(marker, marker + "\n" + entry + "\n", 1)

    ch.write_text(new_text, encoding="utf-8")


def _append_link_definition(pkg_dir: Path, version: Version, repo_slug: str, prev_tag: Optional[str], new_tag: str) -> None:
    """
    Add/append link definition at end:
    [0.1.0]: https://github.com/owner/repo/compare/prev...new
    """
    if not prev_tag:
        return
    ch = _changelog_path(pkg_dir)
    text = ch.read_text(encoding="utf-8").rstrip() + "\n"
    link_line = f"[{version}]: https://github.com/{repo_slug}/compare/{prev_tag}...{new_tag}\n"
    if link_line in text:
        return
    ch.write_text(text + "\n" + link_line, encoding="utf-8")


# ---------------- GitHub API helpers ----------------

def _detect_repo_slug() -> str:
    url = _run(["git", "remote", "get-url", "origin"])
    if url.startswith("git@"):
        slug = url.split(":", 1)[1]
    elif url.startswith("https://") or url.startswith("http://"):
        path = urllib.parse.urlparse(url).path
        slug = path.lstrip("/")
    else:
        raise RuntimeError(f"Unsupported origin URL: {url}")
    return slug.removesuffix(".git")


def _github_headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def _require_token() -> str:
    tok = os.getenv(ENV_GITHUB_TOKEN)
    if not tok:
        raise RuntimeError(f"{ENV_GITHUB_TOKEN} is required for CI checks + GitHub Releases")
    return tok


def _check_ci_green(repo_slug: str, commit_sha: str, token: str) -> bool:
    owner, repo = repo_slug.split("/", 1)

    # 1) combined status
    url_status = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/status"
    r = requests.get(url_status, headers=_github_headers(token), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch commit status: {r.status_code} {r.text}")
    state = r.json().get("state")
    if state != "success":
        print(f"[CI] combined status state={state} for {commit_sha}")
        return False

    # 2) check runs
    url_checks = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/check-runs"
    r2 = requests.get(url_checks, headers=_github_headers(token), timeout=20)
    if r2.status_code != 200:
        raise RuntimeError(f"Failed to fetch check-runs: {r2.status_code} {r2.text}")
    checks = r2.json().get("check_runs", [])
    for c in checks:
        name = c.get("name")
        status = c.get("status")
        conclusion = c.get("conclusion")
        if status != "completed":
            print(f"[CI] check-run {name} status={status} (not completed)")
            return False
        if conclusion != "success":
            print(f"[CI] check-run {name} conclusion={conclusion}")
            return False
    return True


def _create_github_release(repo_slug: str, tag: str, name: str, body: str, token: str, prerelease: bool) -> dict:
    owner, repo = repo_slug.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    payload = {
        "tag_name": tag,
        "name": name,
        "body": body,
        "draft": False,
        "prerelease": prerelease,
    }
    r = requests.post(url, headers=_github_headers(token), json=payload, timeout=20)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create GitHub Release for {tag}: {r.status_code} {r.text}")
    return r.json()


# ---------------- Release planning & apply ----------------

def build_plan_for_pkg(pkg: str, mode: BranchMode) -> ReleasePlan:
    root = _repo_root()
    pkg_dir = root / PACKAGES_DIR / pkg
    pyproject = pkg_dir / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"Missing {pyproject}")

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


def _git_commit_all(message: str) -> None:
    _run(["git", "add", "-A"])
    names = _run(["git", "diff", "--cached", "--name-only"])
    if names.strip():
        _run(["git", "commit", "-m", message])


def _git_tag(tag: str) -> None:
    # idempotent: if tag exists, skip (don't raise)
    if _run(["git", "tag", "--list", tag]).strip():
        print(f"[release] Tag already exists, skipping: {tag}")
        return
    _run(["git", "tag", tag])


def _git_push(branch: str, push_tags: bool) -> None:
    _run(["git", "push", "origin", branch])
    if push_tags:
        _run(["git", "push", "origin", "--tags"])


def apply_plan(plan: ReleasePlan, *, repo_slug: str, token: str, branch: str, push: bool, dry_run: bool) -> Optional[str]:
    if plan.bump == "none":
        return None

    prev_tag = plan.last_tag
    new_tag = _tag_name(plan.pkg, plan.next_version)

    if dry_run:
        print(f"  - would bump {plan.pkg}: {plan.last_version} -> {plan.next_version} ({plan.bump}), tag {new_tag}")
        return new_tag

    # Ensure base commit (current HEAD) is on the expected branch + CI green
    base_commit = _head_sha()
    _ensure_commit_on_branch(base_commit, branch)
    if not _check_ci_green(repo_slug, base_commit, token):
        raise RuntimeError(f"CI not green for commit {base_commit}. Aborting release of {plan.pkg}.")

    # Update pyproject version
    _write_pyproject_version(plan.pyproject, plan.next_version)

    # Update changelog (Keep a Changelog)
    entry = _render_release_entry(plan, repo_slug, new_tag, prev_tag)
    _insert_release_entry_under_unreleased(plan.pkg_dir, entry)
    _append_link_definition(plan.pkg_dir, plan.next_version, repo_slug, prev_tag, new_tag)

    # Commit bump + changelog
    _git_commit_all(f"release({plan.pkg}): {plan.next_version}")

    # Tag & push
    _git_tag(new_tag)

    if push:
        _git_push(branch, push_tags=True)

    # Create GitHub Release notes from changelog entry
    prerelease = (plan.mode == "rc")
    _create_github_release(
        repo_slug=repo_slug,
        tag=new_tag,
        name=f"{plan.pkg} {plan.next_version}",
        body=entry.strip() + ("\n" if entry.strip() else ""),
        token=token,
        prerelease=prerelease,
    )

    return new_tag


def main() -> int:
    ap = argparse.ArgumentParser("Monorepo semantic release tool (local)")
    ap.add_argument("--mode", choices=["rc", "final"], required=True, help="rc => test branch tags; final => master branch tags")
    ap.add_argument("--packages", nargs="*", default=PACKAGES, help="packages to release (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print plan only; do not modify repo")
    ap.add_argument("--push", action="store_true", help="push branch + tags to origin")
    ap.add_argument("--branch", default=None, help="expected branch (defaults based on --mode)")
    ap.add_argument("--force", action="store_true", help="force release even if no changes (defaults to patch bump)")
    ap.add_argument("--force-bump", choices=["patch","minor","major"], default="patch", help="bump level used when --force is set")
    args = ap.parse_args()

    mode: BranchMode = args.mode  # type: ignore
    required_branch = REQUIRED_BRANCH_FOR_MODE[mode]
    branch = args.branch or required_branch

    cur = _current_branch()
    if cur != branch:
        raise RuntimeError(f"Release mode '{mode}' must run on branch '{branch}'. You are on '{cur}'.")

    _ensure_clean()

    # GH repo slug + token
    repo_slug = os.getenv(ENV_GITHUB_REPOSITORY) or DEFAULT_REPO_SLUG or _detect_repo_slug()
    token = _require_token()

    # Enforce HEAD is contained in correct remote branch before anything
    head = _head_sha()
    _ensure_commit_on_branch(head, branch)

    # build plans
    plans = [build_plan_for_pkg(p, mode) for p in args.packages]
    if args.force:
        for pl in plans:
            if pl.bump == "none":
                pl.bump = args.force_bump  # type: ignore
                pl.next_version = _next_version_for_mode(pl.last_version, pl.bump, mode)  # recompute
    else:
        plans = [p for p in plans if p.bump != "none"]

    if not plans:
        print("No package changes detected since last tags. Nothing to release.")
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

    tags: list[str] = []
    for p in plans:
        t = apply_plan(
            p,
            repo_slug=repo_slug,
            token=token,
            branch=branch,
            push=args.push,
            dry_run=False,
        )
        if t:
            tags.append(t)

    print("\n✅ Released tags:")
    for t in tags:
        print(" -", t)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
