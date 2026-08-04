from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import re

from dududa.errors import validation_error
from dududa.domain.primitives import require_aware

from .contracts import RolloutMode


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclass(frozen=True, slots=True)
class RollbackArtifact:
    schema_version: int
    revision: str
    source_path: str
    target_path: str
    tree_digest: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if _REVISION.fullmatch(self.revision) is None:
            raise validation_error("invalid_rollback_artifact_revision")
        for field_name in ("source_path", "target_path"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise validation_error("invalid_rollback_artifact_path", field_name)
        if _DIGEST.fullmatch(self.tree_digest) is None:
            raise validation_error("invalid_rollback_artifact_digest")


@dataclass(frozen=True, slots=True)
class RollbackManifest:
    schema_version: int
    manifest_revision: str
    image_reference: str
    plugin: RollbackArtifact
    config: RollbackArtifact
    control_config_relative_path: str
    target_control_revision: str
    target_rollout_mode: RolloutMode
    compose_file: str
    compose_service: str
    created_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if _REVISION.fullmatch(self.manifest_revision) is None:
            raise validation_error("invalid_rollback_manifest_revision")
        if re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", self.image_reference) is None:
            raise validation_error("rollback_image_must_be_digest_pinned")
        if not isinstance(self.plugin, RollbackArtifact) or not isinstance(
            self.config, RollbackArtifact
        ):
            raise validation_error("invalid_rollback_artifact")
        if (
            not isinstance(self.control_config_relative_path, str)
            or not self.control_config_relative_path.strip()
            or self.control_config_relative_path.startswith(("/", "\\"))
            or ".." in self.control_config_relative_path.replace("\\", "/").split("/")
        ):
            raise validation_error("invalid_rollback_control_config_path")
        if _REVISION.fullmatch(self.target_control_revision) is None:
            raise validation_error("invalid_rollback_control_revision")
        if self.target_rollout_mode is not RolloutMode.OFF:
            raise validation_error("rollback_target_mode_must_be_off")
        for field_name in ("compose_file", "compose_service"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise validation_error("invalid_rollback_compose_field", field_name)
        require_aware(self.created_at, "rollback_manifest_created_at")


def parse_rollback_manifest(value: Mapping[str, object]) -> RollbackManifest:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_rollback_manifest")
    expected = {
        "schema_version",
        "manifest_revision",
        "image_reference",
        "plugin",
        "config",
        "control_config_relative_path",
        "target_control_revision",
        "target_rollout_mode",
        "compose_file",
        "compose_service",
        "created_at",
    }
    if set(value) != expected:
        raise validation_error("invalid_rollback_manifest_fields")
    mode = value["target_rollout_mode"]
    try:
        parsed_mode = RolloutMode(mode) if isinstance(mode, str) else None
    except ValueError:
        parsed_mode = None
    if parsed_mode is None:
        raise validation_error("invalid_rollout_mode")
    created_at = value["created_at"]
    if not isinstance(created_at, str):
        raise validation_error("invalid_rollback_manifest_time")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        raise validation_error("invalid_rollback_manifest_time") from None
    return RollbackManifest(
        schema_version=_integer(value["schema_version"]),
        manifest_revision=_string(value["manifest_revision"]),
        image_reference=_string(value["image_reference"]),
        plugin=_artifact(value["plugin"]),
        config=_artifact(value["config"]),
        control_config_relative_path=_string(value["control_config_relative_path"]),
        target_control_revision=_string(value["target_control_revision"]),
        target_rollout_mode=parsed_mode,
        compose_file=_string(value["compose_file"]),
        compose_service=_string(value["compose_service"]),
        created_at=parsed_created_at,
    )


def _artifact(value: object) -> RollbackArtifact:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "revision",
        "source_path",
        "target_path",
        "tree_digest",
    }:
        raise validation_error("invalid_rollback_artifact")
    return RollbackArtifact(
        _integer(value["schema_version"]),
        _string(value["revision"]),
        _string(value["source_path"]),
        _string(value["target_path"]),
        _string(value["tree_digest"]),
    )


def _integer(value: object) -> int:
    if type(value) is not int:
        raise validation_error("invalid_rollback_integer")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_rollback_string")
    return value


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
