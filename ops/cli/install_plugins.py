#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "third_party" / "plugins.lock.json"
OWNED_PLUGIN_PATHS = (
    "apps/astrbot-plugins/astrbot_plugin_dududa_core",
    "apps/astrbot-plugins/astrbot_plugin_proactive_chatter",
    "apps/astrbot-plugins/astrbot_plugin_reread",
    "apps/astrbot-plugins/astrbot_plugin_reply_review",
    "apps/astrbot-plugins/astrbot_plugin_sub2api_readonly",
    "apps/astrbot-plugins/astrbot_plugin_ustc_shuttle",
    "apps/astrbot-plugins/astrbot_plugin_weather",
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MARKER_PATH_ALIASES = {
    "vendor/astrbot_plugin_better_reminder": (
        "third_party/vendor/astrbot_plugin_better_reminder"
    ),
    "patches/iris-memory-user-group-isolation.patch": (
        "third_party/patches/iris-memory-user-group-isolation.patch"
    ),
}


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def marker_for(plugin: dict) -> dict:
    return {
        key: plugin[key]
        for key in (
            "name",
            "version",
            "source",
            "repository",
            "commit",
            "patch",
            "path",
            "sparse_paths",
        )
        if key in plugin
    }


def canonical_marker(marker: dict) -> dict:
    normalized = dict(marker)
    for key in ("path", "patch"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = MARKER_PATH_ALIASES.get(value, value)
    return normalized


def marker_matches(target: Path, plugin: dict) -> bool:
    marker_path = target / ".dududa-lock.json"
    if not marker_path.is_file():
        return False
    try:
        stored = json.loads(marker_path.read_text(encoding="utf-8"))
        return isinstance(stored, dict) and canonical_marker(
            stored
        ) == canonical_marker(marker_for(plugin))
    except json.JSONDecodeError:
        return False


def write_marker(target: Path, plugin: dict) -> None:
    (target / ".dududa-lock.json").write_text(
        json.dumps(marker_for(plugin), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def stage_plugin(plugin: dict, plugins_root: Path) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=f".{plugin['name']}.", dir=plugins_root))
    try:
        source = plugin["source"]
        if source == "vendor":
            vendor_path = (REPO_ROOT / plugin["path"]).resolve()
            if REPO_ROOT not in vendor_path.parents or not vendor_path.is_dir():
                raise RuntimeError(f"invalid vendor path for {plugin['name']}")
            shutil.copytree(
                vendor_path,
                staging,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
            )
            return staging

        if source != "git":
            raise RuntimeError(f"unsupported plugin source: {source}")
        commit = plugin.get("commit", "")
        if not COMMIT_RE.fullmatch(commit):
            raise RuntimeError(f"invalid commit for {plugin['name']}: {commit}")
        remove_path(staging)
        run(
            "git",
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--no-tags",
            "--no-checkout",
            plugin["repository"],
            str(staging),
        )
        sparse_paths = plugin.get("sparse_paths")
        if sparse_paths:
            if not isinstance(sparse_paths, list) or not all(
                isinstance(path, str)
                and path
                and not path.startswith("/")
                and ".." not in Path(path).parts
                for path in sparse_paths
            ):
                raise RuntimeError(f"invalid sparse_paths for {plugin['name']}")
            run("git", "sparse-checkout", "init", "--cone", cwd=staging)
            run("git", "sparse-checkout", "set", *sparse_paths, cwd=staging)
        run("git", "checkout", "--quiet", "--detach", commit, cwd=staging)
        if patch_name := plugin.get("patch"):
            patch_path = (REPO_ROOT / patch_name).resolve()
            if REPO_ROOT not in patch_path.parents or not patch_path.is_file():
                raise RuntimeError(f"invalid patch path for {plugin['name']}")
            run("git", "apply", "--check", str(patch_path), cwd=staging)
            run("git", "apply", str(patch_path), cwd=staging)
        shutil.rmtree(staging / ".git")
        return staging
    except Exception:
        remove_path(staging)
        raise


def install_plugin(plugin: dict, plugins_root: Path, force: bool) -> None:
    target = plugins_root / plugin["name"]
    if marker_matches(target, plugin) and not force:
        print(f"locked plugin is current: {plugin['name']}")
        return
    if target.exists() and not force:
        raise RuntimeError(
            f"{target} exists without the expected lock marker; rerun with --force after reviewing local changes"
        )

    staging = stage_plugin(plugin, plugins_root)
    backup = plugins_root / f".{plugin['name']}.previous"
    try:
        write_marker(staging, plugin)
        remove_path(backup)
        if target.exists() or target.is_symlink():
            target.replace(backup)
        staging.replace(target)
        remove_path(backup)
        print(f"installed locked plugin: {plugin['name']} ({plugin['version']})")
    except Exception:
        if not target.exists() and backup.exists():
            backup.replace(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def install_owned_plugin(relative_path: str, plugins_root: Path) -> None:
    source = (REPO_ROOT / relative_path).resolve()
    if REPO_ROOT not in source.parents or not source.is_dir():
        raise RuntimeError(f"invalid owned plugin path: {relative_path}")
    target = plugins_root / source.name
    staging = Path(tempfile.mkdtemp(prefix=f".{source.name}.", dir=plugins_root))
    backup = plugins_root / f".{source.name}.previous"
    try:
        shutil.copytree(
            source,
            staging,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
        )
        (staging / ".dududa-owned.json").write_text(
            json.dumps(
                {"schema_version": 1, "name": source.name, "path": relative_path},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        remove_path(backup)
        if target.exists() or target.is_symlink():
            target.replace(backup)
        staging.replace(target)
        remove_path(backup)
        print(f"installed owned plugin: {source.name}")
    except Exception:
        if not target.exists() and backup.exists():
            backup.replace(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Dududa AstrBot plugins.")
    root = parser.add_mutually_exclusive_group(required=True)
    root.add_argument("--data-root", type=Path)
    root.add_argument("--plugins-root", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--owned-only", action="store_true")
    args = parser.parse_args()

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1 or not isinstance(lock.get("plugins"), list):
        raise RuntimeError(f"unsupported lock file: {LOCK_PATH}")
    plugins_root = (
        args.plugins_root.expanduser().resolve()
        if args.plugins_root is not None
        else args.data_root.expanduser().resolve() / "astrbot" / "plugins"
    )
    plugins_root.mkdir(parents=True, exist_ok=True)
    for relative_path in OWNED_PLUGIN_PATHS:
        install_owned_plugin(relative_path, plugins_root)
    if not args.owned_only:
        for plugin in lock["plugins"]:
            install_plugin(plugin, plugins_root, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
