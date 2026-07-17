#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", "data", "runtime", "node_modules"}
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519", "auth.json"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".dump", ".pem", ".p12", ".pfx"}
MAX_FILE_SIZE = 10 * 1024 * 1024
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def iter_files():
    if (ROOT / ".git").exists():
        output = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
        )
        for raw_path in output.split(b"\0"):
            if not raw_path:
                continue
            path = ROOT / raw_path.decode("utf-8", errors="surrogateescape")
            if path.is_file():
                yield path
        return
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in iter_files():
        checked += 1
        relative = path.relative_to(ROOT)
        if path.name in FORBIDDEN_NAMES:
            failures.append(f"forbidden file name: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden runtime/secret suffix: {relative}")
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            failures.append(f"file exceeds 10 MiB: {relative} ({size} bytes)")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"possible {label}: {relative}")
    if failures:
        print("repository safety check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"repository safety check passed ({checked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
