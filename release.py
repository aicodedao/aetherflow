#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
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

# breaking bumps MINOR (not major) per your setup
BREAKING_BUMPS: Bump = "minor"

# when there are changes but no conventional commit signals
DEFAULT_BUMP_IF_CHANGES: Bump = "patch"

# tags like: <pkg>-v0.1.0 / <pkg>-v0.1.0rc1
TAG_PREFIX_FMT = "{pkg}-v"

# required branches for each mode (can override via --branch)
REQUIRED_BRANCH_FOR_MODE = {"rc": "test", "final": "master"}

# ---- tokens (IMPORTANT) ----
# If you use the default Actions GITHUB_TOKEN to create tags/refs,
# GitHub may NOT trigger other workflows (publish-on-tag) to avoid infinite loops.
# Best practice: create a PAT / fine-grained token that has "contents:write" + "workflow" perms,
# store as secret RELEASE_TOKEN, and set env RELEASE_TOKEN in workflows.
ENV_RELEASE_TOKEN = "RELEASE_TOKEN"  # preferred
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"  # fallback (works for PR/merge, but may NOT trigger publish workflow)
ENV_GITHUB_REPOSITORY = "GITHUB_REPOSITORY"  # usually "owner/repo" in Actions

DEFAULT_REPO_SLUG = "aicodedao/aetherflow"
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
    typ: str  # feat/fix/perf/docs/refactor/chore/ci/build/test/other
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


# ---------------- misc helpers ----------------
def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


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


def _ensure_clean(*, allow_dirty: bool = False) -> None:
    st = _run(["git", "status", "--porcelain"])
    if st.strip() and not allow_dirty:
        raise RuntimeError(f"Working tree dirty. Commit/stash first.\n{st}")


def _current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _head_sha(ref: str = "HEAD") -> str:
    return _run(["git", "rev-parse", ref])


def _fetch_all() -> None:
    _run(["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"])
    _run(["git", "fetch", "--tags", "origin"])


def _remote_branches_containing(commit: str) -> list[str]:
    out = _run(["git", "branch", "-r", "--contains", commit])
    return [x.strip() for x in out.splitlines() if x.strip()]


def _ensure_commit_on_branch(commit: str, branch: str) -> None:
    """
    Enforce "origin/<branch> contains commit".
    Use ONLY for base branch commit BEFORE making release commits.
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


def _git_branch_exists_local(branch: str) -> bool:
    p = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return p.returncode == 0


def _git_checkout_or_create_branch_from(branch: str, base_ref: str) -> None:
    """
    Idempotent:
    - if branch exists: checkout + reset to base_ref
    - else: create from base_ref
    """
    _run(["git", "checkout", base_ref])
    if _git_branch_exists_local(branch):
        _run(["git", "checkout", branch])
        _run(["git", "reset", "--hard", base_ref])
        return
    _run(["git", "checkout", "-b", branch, base_ref])


def _git_push_branch_upsert(branch: str) -> None:
    """
    If first time: push -u
    If already exists on remote: force-with-lease to update safely
    """
    p = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if p.returncode == 0:
        _run(["git", "push", "--force-with-lease", "origin", f"HEAD:refs/heads/{branch}"])
    else:
        _run(["git", "push", "-u", "origin", branch])


def _git_commit_all(message: str) -> None:
    _run(["git", "add", "-A"])
    names = _run(["git", "diff", "--cached", "--name-only"])
    if names.strip():
        _run(["git", "commit", "-m", message])


def _make_release_branch_name(*, mode: BranchMode, base_sha: str) -> str:
    """
    Unique per workflow-run to avoid collisions on reruns:
    - includes GITHUB_RUN_ID + GITHUB_RUN_ATTEMPT when available.
    """
    run_id = _env("GITHUB_RUN_ID", "local")
    run_attempt = _env("GITHUB_RUN_ATTEMPT", "0")
    short = base_sha[:7]
    ymd = date.today().isoformat().replace("-", "")
    return f"release/{mode}-{ymd}-{short}-{run_id}-{run_attempt}"


def _list_tags() -> list[str]:
    out = _run(["git", "tag", "--list"])
    return [t for t in out.splitlines() if t.strip()]


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


def _first_commit() -> str:
    out = _run(["git", "rev-list", "--max-parents=0", "HEAD"])
    commits = [x.strip() for x in out.splitlines() if x.strip()]
    if not commits:
        raise RuntimeError("Cannot determine first commit (repo has no commits?)")
    return commits[-1]


def _rev_range_since(tag: Optional[str]) -> Optional[str]:
    return f"{tag}..HEAD" if tag else None


def _changed_files_since(tag: Optional[str], path_prefix: str) -> list[str]:
    rr = _rev_range_since(tag)
    if rr:
        out = _run(["git", "diff", "--name-only", rr, "--", path_prefix])
    else:
        base = _first_commit()
        out = _run(["git", "diff", "--name-only", f"{base}..HEAD", "--", path_prefix])
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
    If no tag exists, include full history for that path.
    """
    fmt = "%H%n%s%n%b%n==END=="
    rr = _rev_range_since(tag)

    if rr:
        out = _run(["git", "log", rr, "--pretty=format:" + fmt, "--", path_prefix])
    else:
        out = _run(["git", "log", "--pretty=format:" + fmt, "--", path_prefix])

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

    if last.rc is not None and (last.major, last.minor, last.patch) == (bumped.major, bumped.minor, bumped.patch):
        return bumped.to_rc(last.rc + 1)
    return bumped.to_rc(1)


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
    title = f"## [{plan.next_version}] - {date.today().isoformat()}"
    groups: dict[str, list[CommitEntry]] = {}

    for c in plan.commits:
        groups.setdefault(c.typ, []).append(c)

    def bullet(c: CommitEntry) -> str:
        scope = f"**{c.scope}**: " if c.scope else ""
        breaking = " **(BREAKING)**" if c.breaking else ""
        short = c.sha[:7]
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
            raise RuntimeError(f"CHANGELOG.md missing [Unreleased] section in {pkg_dir}")

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
    tok = os.getenv(ENV_RELEASE_TOKEN) or os.getenv(ENV_GITHUB_TOKEN)
    if not tok:
        raise RuntimeError(
            f"Missing token. Set {ENV_RELEASE_TOKEN} (preferred) or {ENV_GITHUB_TOKEN}.\n"
            f"Note: {ENV_GITHUB_TOKEN} may NOT trigger tag-based publish workflows."
        )
    return tok


def _github_api_base(repo_slug: str) -> str:
    owner, repo = repo_slug.split("/", 1)
    return f"https://api.github.com/repos/{owner}/{repo}"


def _check_ci_green(repo_slug: str, commit_sha: str, token: str) -> bool:
    owner, repo = repo_slug.split("/", 1)
    url_status = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/status"
    url_checks = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/check-runs"

    deadline = time.time() + 240  # 4 min
    last_state = None

    while time.time() < deadline:
        r = requests.get(url_status, headers=_github_headers(token), timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"Failed to fetch commit status: {r.status_code} {r.text}")
        state = r.json().get("state")
        last_state = state

        if state != "success":
            print(f"[CI] combined status state={state} for {commit_sha} (waiting...)")
            time.sleep(5)
            continue

        r2 = requests.get(url_checks, headers=_github_headers(token), timeout=20)
        if r2.status_code != 200:
            raise RuntimeError(f"Failed to fetch check-runs: {r2.status_code} {r2.text}")

        checks = r2.json().get("check_runs", [])
        if not checks:
            print(f"[CI] check-runs not visible yet for {commit_sha} (waiting...)")
            time.sleep(5)
            continue

        all_completed = True
        all_success = True
        for c in checks:
            name = c.get("name")
            status = c.get("status")
            conclusion = c.get("conclusion")
            if status != "completed":
                all_completed = False
                all_success = False
                print(f"[CI] check-run {name} status={status} (waiting...)")
                break
            if conclusion != "success":
                all_success = False
                print(f"[CI] check-run {name} conclusion={conclusion}")
                break

        if all_completed and all_success:
            return True

        time.sleep(5)

    print(f"[CI] timeout waiting for CI to be green. last_state={last_state}")
    return False


def _github_create_pr(*, repo_slug: str, token: str, head: str, base: str, title: str, body: str) -> dict:
    url = _github_api_base(repo_slug) + "/pulls"
    payload = {"title": title, "head": head, "base": base, "body": body}
    r = requests.post(url, headers=_github_headers(token), json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create PR: {r.status_code} {r.text}")
    return r.json()


def _github_get_pr(*, repo_slug: str, token: str, pr_number: int) -> dict:
    url = _github_api_base(repo_slug) + f"/pulls/{pr_number}"
    r = requests.get(url, headers=_github_headers(token), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to get PR: {r.status_code} {r.text}")
    return r.json()


def _github_merge_pr(*, repo_slug: str, token: str, pr_number: int, method: str) -> dict:
    url = _github_api_base(repo_slug) + f"/pulls/{pr_number}/merge"
    payload = {"merge_method": method}
    r = requests.put(url, headers=_github_headers(token), json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Failed to merge PR #{pr_number}: {r.status_code} {r.text}")
    return r.json()


def _github_create_lightweight_tag(*, repo_slug: str, token: str, tag: str, sha: str) -> None:
    url = _github_api_base(repo_slug) + "/git/refs"
    payload = {"ref": f"refs/tags/{tag}", "sha": sha}
    r = requests.post(url, headers=_github_headers(token), json=payload, timeout=30)
    if r.status_code in (200, 201):
        return
    if r.status_code == 422 and "Reference already exists" in r.text:
        print(f"[release] Tag already exists on remote, skipping: {tag}")
        return
    raise RuntimeError(f"Failed to create tag ref {tag}: {r.status_code} {r.text}")


def _create_github_release(repo_slug: str, tag: str, name: str, body: str, token: str, prerelease: bool) -> dict:
    url = _github_api_base(repo_slug) + "/releases"
    payload = {
        "tag_name": tag,
        "name": name,
        "body": body,
        "draft": False,
        "prerelease": prerelease,
    }
    r = requests.post(url, headers=_github_headers(token), json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create GitHub Release for {tag}: {r.status_code} {r.text}")
    return r.json()


def _github_find_open_pr(*, repo_slug: str, token: str, head_branch: str, base: str) -> Optional[dict]:
    """
    Find open PR by head+base. head must be "owner:branch" on GitHub API filters.
    """
    owner, _ = repo_slug.split("/", 1)
    head_q = f"{owner}:{head_branch}"
    url = _github_api_base(repo_slug) + (
        f"/pulls?state=open&head={urllib.parse.quote(head_q)}&base={urllib.parse.quote(base)}"
    )
    r = requests.get(url, headers=_github_headers(token), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to list PRs: {r.status_code} {r.text}")
    prs = r.json() or []
    return prs[0] if prs else None


def _github_is_pr_merged(*, repo_slug: str, token: str, pr_number: int) -> bool:
    url = _github_api_base(repo_slug) + f"/pulls/{pr_number}/merge"
    r = requests.get(url, headers=_github_headers(token), timeout=30)
    if r.status_code == 204:
        return True
    if r.status_code == 404:
        return False
    raise RuntimeError(f"Failed to check PR merge status: {r.status_code} {r.text}")


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


def apply_plan(plan: ReleasePlan, *, repo_slug: str, dry_run: bool) -> tuple[Optional[str], str]:
    """
    PR-based flow:
    - Modify files + commit (on CURRENT branch = release branch).
    - DO NOT tag.
    Returns (tag, entry_body). If bump==none => (None, "").
    """
    if plan.bump == "none":
        return None, ""

    prev_tag = plan.last_tag
    new_tag = _tag_name(plan.pkg, plan.next_version)
    entry = _render_release_entry(plan, repo_slug, new_tag, prev_tag)

    if dry_run:
        print(f"  - would bump {plan.pkg}: {plan.last_version} -> {plan.next_version} ({plan.bump}), tag {new_tag}")
        return new_tag, entry

    _write_pyproject_version(plan.pyproject, plan.next_version)
    _insert_release_entry_under_unreleased(plan.pkg_dir, entry)
    _append_link_definition(plan.pkg_dir, plan.next_version, repo_slug, prev_tag, new_tag)
    _git_commit_all(f"release({plan.pkg}): {plan.next_version}")

    return new_tag, entry


def main() -> int:
    ap = argparse.ArgumentParser("Monorepo semantic release tool (PR-based for protected branches)")
    ap.add_argument("--mode", choices=["rc", "final"], required=True, help="rc => test branch; final => master branch")
    ap.add_argument("--packages", nargs="*", default=PACKAGES, help="packages to release (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print plan only; do not modify repo")
    ap.add_argument("--push", action="store_true", help="push via PR + merge + tag-after-merge")
    ap.add_argument("--push-via-pr", action="store_true", help="REQUIRED for protected branches")
    ap.add_argument("--no-auto-merge", action="store_true", help="create PR but do not auto-merge")
    ap.add_argument("--pr-merge-method", choices=["merge", "squash", "rebase"], default="merge")
    ap.add_argument("--branch", default=None, help="expected base branch (defaults based on --mode)")
    ap.add_argument("--force", action="store_true", help="force release even if no changes")
    ap.add_argument("--force-bump", choices=["patch", "minor", "major"], default="patch")
    ap.add_argument("--allow-dirty", action="store_true", help="allow running with uncommitted changes (LOCAL TEST ONLY)")
    ap.add_argument("--skip-ci-check", action="store_true", help="skip waiting for CI green")
    args = ap.parse_args()

    mode: BranchMode = args.mode  # type: ignore
    base_branch = args.branch or REQUIRED_BRANCH_FOR_MODE[mode]

    _fetch_all()  # make sure tags/branches are fresh

    cur = _current_branch()
    if cur != base_branch:
        raise RuntimeError(f"Release mode '{mode}' must run on branch '{base_branch}'. You are on '{cur}'.")

    _ensure_clean(allow_dirty=args.allow_dirty)

    repo_slug = os.getenv(ENV_GITHUB_REPOSITORY) or DEFAULT_REPO_SLUG or _detect_repo_slug()
    token = _require_token()

    # Enforce base commit belongs to the expected remote branch before making release commits.
    base_sha = _head_sha("HEAD")
    _ensure_commit_on_branch(base_sha, base_branch)

    # Optional: ensure CI green on base commit (workflow_run already implies this, but keep for local safety)
    if not args.skip_ci_check:
        ok = _check_ci_green(repo_slug, base_sha, token)
        if not ok:
            raise RuntimeError(f"CI not green for base commit {base_sha}. Aborting.")

    plans = [build_plan_for_pkg(p, mode) for p in args.packages]
    if args.force:
        for pl in plans:
            if pl.bump == "none":
                pl.bump = args.force_bump  # type: ignore
                pl.next_version = _next_version_for_mode(pl.last_version, pl.bump, mode)
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

    # If pushing: do PR-based flow on a release branch.
    rel_branch = None
    if args.push:
        if not args.push_via_pr:
            raise RuntimeError(
                "Repo ruleset says: changes must be made through a pull request.\n"
                "Run with: --push --push-via-pr"
            )

        rel_branch = _make_release_branch_name(mode=mode, base_sha=base_sha)
        # critical: create/checkout release branch from base branch BEFORE making release commits
        _git_checkout_or_create_branch_from(rel_branch, base_branch)
    else:
        # no push: just commit on base branch (local only)
        rel_branch = None

    tags: list[str] = []
    entries_by_tag: dict[str, str] = {}

    for p in plans:
        t, entry = apply_plan(p, repo_slug=repo_slug, dry_run=False)
        if t:
            tags.append(t)
            entries_by_tag[t] = entry

    if not tags:
        print("No releases produced.")
        return 0

    if not args.push:
        print("\n✅ Local commits created (no push). Planned tags:")
        for t in tags:
            print(" -", t)
        return 0

    assert rel_branch is not None

    # Push branch (idempotent)
    _git_push_branch_upsert(rel_branch)

    # Create or reuse PR
    existing = _github_find_open_pr(repo_slug=repo_slug, token=token, head_branch=rel_branch, base=base_branch)
    if existing:
        pr_number = existing["number"]
        pr_url = existing.get("html_url", "")
        print(f"\n✅ Reusing existing PR #{pr_number}: {pr_url}")
        pr = existing
    else:
        pr_title = f"Release {mode}: " + ", ".join(tags)
        pr_body = (
                f"Automated release PR for mode={mode}.\n\n"
                f"- Base branch: `{base_branch}`\n"
                f"- Release branch: `{rel_branch}`\n\n"
                "Tags to be created after merge:\n"
                + "\n".join([f"- `{t}`" for t in tags])
                + "\n"
        )
        pr = _github_create_pr(
            repo_slug=repo_slug,
            token=token,
            head=rel_branch,
            base=base_branch,
            title=pr_title,
            body=pr_body,
        )
        pr_number = pr["number"]
        pr_url = pr.get("html_url", "")
        print(f"\n✅ Created PR #{pr_number}: {pr_url}")

    if args.no_auto_merge:
        print("\nAuto-merge disabled. Merge the PR manually, then rerun release to create tags.")
        return 0

    # If already merged (rerun), skip merge and just tag
    if _github_is_pr_merged(repo_slug=repo_slug, token=token, pr_number=pr_number):
        pr2 = _github_get_pr(repo_slug=repo_slug, token=token, pr_number=pr_number)
        merge_sha = pr2.get("merge_commit_sha")
        if not merge_sha:
            raise RuntimeError("PR is merged but merge_commit_sha is missing.")
        print(f"\n✅ PR already merged. merge_commit_sha={merge_sha}")
    else:
        # Refresh PR object (ensure we have current head sha)
        pr2 = _github_get_pr(repo_slug=repo_slug, token=token, pr_number=pr_number)
        pr_head_sha = pr2["head"]["sha"]

        if not args.skip_ci_check:
            ok = _check_ci_green(repo_slug, pr_head_sha, token)
            if not ok:
                raise RuntimeError(f"CI not green for PR head {pr_head_sha}. Aborting merge.")

        merge = _github_merge_pr(
            repo_slug=repo_slug,
            token=token,
            pr_number=pr_number,
            method=args.pr_merge_method,
        )
        merge_sha = merge.get("sha") or pr2.get("merge_commit_sha")
        if not merge_sha:
            # one more refresh
            pr3 = _github_get_pr(repo_slug=repo_slug, token=token, pr_number=pr_number)
            merge_sha = pr3.get("merge_commit_sha")
        if not merge_sha:
            raise RuntimeError("Cannot determine merge commit SHA after merge.")
        print(f"\n✅ PR merged. merge_commit_sha={merge_sha}")

    # Tag + GitHub Release (idempotent)
    prerelease = (mode == "rc")
    for t in tags:
        _github_create_lightweight_tag(repo_slug=repo_slug, token=token, tag=t, sha=merge_sha)
        body = entries_by_tag.get(t, "").strip()
        _create_github_release(
            repo_slug=repo_slug,
            tag=t,
            name=t,
            body=body + ("\n" if body else ""),
            token=token,
            prerelease=prerelease,
        )

    print("\n✅ Released tags:")
    for t in tags:
        print(" -", t)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
