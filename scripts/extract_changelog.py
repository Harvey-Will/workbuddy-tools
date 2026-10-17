#!/usr/bin/env python3
"""Extract release notes for a given version tag from CHANGELOG.md."""
import re
import sys
from pathlib import Path


def extract(tag: str, changelog_path: Path) -> str:
    if not changelog_path.exists():
        return ""
    text = changelog_path.read_text(encoding="utf-8")
    clean_tag = tag.strip().lstrip("v")
    
    # Match heading like: ## [v0.1.5.2] or ## [0.1.5.2]
    pattern = rf"##\s*\[v?{re.escape(clean_tag)}\][^\n]*\n([\s\S]*?)(?=\n##\s*\[|\Z)"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return ""


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    root = Path(__file__).resolve().parents[1]
    changelog = root / "CHANGELOG.md"
    out_file = root / "release_notes.md"
    
    notes = extract(tag, changelog)
    if not notes:
        notes = f"Release {tag}"
        
    out_file.write_text(notes, encoding="utf-8")
    print(f"Extracted {len(notes)} chars of release notes for {tag} to {out_file}")


if __name__ == "__main__":
    main()
