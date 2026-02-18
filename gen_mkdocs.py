# gen_mkdocs.py
import yaml
from pathlib import Path
import re

MKDOCS_YML = Path("mkdocs.yaml")
DOCS_DIR = Path("docs")

def pretty_label(path: Path) -> str:
    stem = path.stem
    # remove numeric prefix like "00-foo-bar" -> "foo-bar"
    m = re.match(r"^(\d+)[-_](.+)$", stem)
    if m:
        label = m.group(2)
    else:
        label = stem
    # replace dashes/underscores with spaces and Title Case
    return label.replace("-", " ").replace("_", " ").strip().title()

def collect_md_files(docs_dir: Path):
    files = [p for p in docs_dir.rglob("*.md") if not p.name.startswith("_")]
    # ignore index.md because it's the home page (we'll put it first)
    index = [p for p in files if p.resolve() == (docs_dir / "index.md").resolve()]
    others = [p for p in files if p.resolve() != (docs_dir / "index.md").resolve()]
    # sort by numeric prefix, then name
    def sort_key(p: Path):
        name = p.stem
        m = re.match(r"^(\d+)[-_].*$", name)
        if m:
            return (int(m.group(1)), name)
        return (9999, name)
    others.sort(key=sort_key)
    return index + others

def build_nav(md_files, docs_dir: Path):
    nav = []
    # Put index first as "Home"
    for p in md_files:
        rel = p.relative_to(docs_dir).as_posix()
        if rel.lower() == "index.md":
            nav.append({"Home": rel})
        else:
            nav.append({pretty_label(p): rel})
    return nav

def main():
    if not MKDOCS_YML.exists():
        raise SystemExit("mkdocs.yml not found in repo root.")
    if not DOCS_DIR.exists():
        raise SystemExit("docs/ directory not found.")
    # read mkdocs.yml
    with MKDOCS_YML.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    md_files = collect_md_files(DOCS_DIR)
    nav = build_nav(md_files, DOCS_DIR)

    # inject nav
    cfg["nav"] = nav

    # backup and write
    backup = MKDOCS_YML.with_suffix(".yaml.bak")
    MKDOCS_YML.replace(backup)  # make backup
    with MKDOCS_YML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

    print(f"mkdocs.yml updated with {len(nav)} nav entries (backup -> {backup})")

if __name__ == "__main__":
    main()
