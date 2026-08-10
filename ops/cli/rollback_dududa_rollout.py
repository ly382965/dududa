#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
AGENT_SRC = ROOT / "packages" / "dududa-agent" / "src"
if str(AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(AGENT_SRC))

from dududa.rollout import RollbackManifest, parse_rollback_manifest  # noqa: E402


def tree_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"artifact is not a regular directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"artifact contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content_digest = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(content_digest)
    return f"sha256:{digest.hexdigest()}"


def load_manifest(path: Path) -> RollbackManifest:
    value = json.loads(path.read_text(encoding="utf-8"))
    return parse_rollback_manifest(value)


def resolve_artifact_paths(manifest_path: Path, manifest: RollbackManifest):
    base = manifest_path.parent

    def resolve(value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else base / path).resolve()

    return (
        resolve(manifest.plugin.source_path),
        resolve(manifest.plugin.target_path),
        resolve(manifest.config.source_path),
        resolve(manifest.config.target_path),
    )


def verify(manifest_path: Path, manifest: RollbackManifest) -> tuple[Path, ...]:
    plugin_source, plugin_target, config_source, config_target = resolve_artifact_paths(
        manifest_path, manifest
    )
    if plugin_source == plugin_target or config_source == config_target:
        raise ValueError("rollback source and target must differ")
    if _overlap(plugin_target, config_target):
        raise ValueError("plugin and config rollback targets must not overlap")
    for target in (plugin_target, config_target):
        if target == Path(target.anchor):
            raise ValueError("rollback target cannot be a filesystem root")
    if tree_digest(plugin_source) != manifest.plugin.tree_digest:
        raise ValueError("plugin artifact digest mismatch")
    if tree_digest(config_source) != manifest.config.tree_digest:
        raise ValueError("config artifact digest mismatch")
    compose_file = Path(manifest.compose_file)
    if not compose_file.is_absolute():
        compose_file = (manifest_path.parent / compose_file).resolve()
    if not compose_file.is_file():
        raise ValueError("rollback compose file does not exist")
    control_path = config_source / manifest.control_config_relative_path
    control = json.loads(control_path.read_text(encoding="utf-8"))
    expected = {
        "rollout_mode": "off",
        "rollout_delivery_enabled": False,
        "rollout_kill_switch": True,
        "rollout_revision": manifest.target_control_revision,
    }
    if not isinstance(control, dict) or any(
        control.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("rollback config does not contain the required off controls")
    return plugin_source, plugin_target, config_source, config_target


def apply(
    manifest_path: Path,
    manifest: RollbackManifest,
    backup_root: Path,
) -> None:
    plugin_source, plugin_target, config_source, config_target = verify(
        manifest_path, manifest
    )
    backup_root.mkdir(parents=True, exist_ok=False)
    swaps: list[tuple[Path, Path | None]] = []
    try:
        for name, source, target in (
            ("config", config_source, config_target),
            ("plugin", plugin_source, plugin_target),
        ):
            old = _replace_tree(source, target)
            swaps.append((target, old))
            if old is not None:
                shutil.copytree(old, backup_root / name)
        environment = dict(os.environ)
        environment["DUDUDA_ASTRBOT_IMAGE"] = manifest.image_reference
        compose_file = Path(manifest.compose_file)
        if not compose_file.is_absolute():
            compose_file = (manifest_path.parent / compose_file).resolve()
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                manifest.compose_service,
            ],
            check=True,
            env=environment,
        )
    except BaseException:
        for target, old in reversed(swaps):
            _restore_tree(target, old)
        raise
    else:
        for _, old in swaps:
            if old is not None:
                shutil.rmtree(old)


def _replace_tree(source: Path, target: Path) -> Path | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.rollback-new-{uuid4().hex}"
    old = target.parent / f".{target.name}.rollback-old-{uuid4().hex}"
    shutil.copytree(source, staging)
    existing: Path | None = None
    try:
        if target.exists():
            os.replace(target, old)
            existing = old
        os.replace(staging, target)
    except BaseException:
        if target.exists():
            shutil.rmtree(target)
        if existing is not None and existing.exists():
            os.replace(existing, target)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return existing


def _restore_tree(target: Path, old: Path | None) -> None:
    if target.exists():
        shutil.rmtree(target)
    if old is not None and old.exists():
        os.replace(old, target)


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate or apply a Dududa S11 rollout rollback manifest."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    verify(manifest_path, manifest)
    if args.apply:
        if args.backup_dir is None:
            parser.error("--apply requires --backup-dir")
        apply(manifest_path, manifest, args.backup_dir.resolve())
        print("rollback applied; runtime control is off")
    else:
        print("rollback manifest and artifact digests are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
