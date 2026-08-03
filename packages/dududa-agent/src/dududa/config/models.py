from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from dududa.errors import DududaError, ErrorCategory, ErrorInfo


class ConfigError(DududaError):
    pass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    schema_version: int
    default_persona_id: str
    policy_snapshot_id: str
    feature_flags: Mapping[str, bool]


def parse_agent_config(value: object) -> AgentConfig:
    if not isinstance(value, Mapping):
        raise _config_error("config_not_mapping")
    allowed = {
        "schema_version",
        "default_persona_id",
        "policy_snapshot_id",
        "feature_flags",
    }
    unknown = set(value) - allowed
    if unknown:
        raise _config_error("unknown_config_field", *sorted(map(str, unknown)))
    version = value.get("schema_version")
    persona = value.get("default_persona_id")
    policy = value.get("policy_snapshot_id")
    flags = value.get("feature_flags", {})
    if type(version) is not int or version != 1:
        raise _config_error("unsupported_config_version")
    if not isinstance(persona, str) or not persona.strip():
        raise _config_error("invalid_default_persona")
    if not isinstance(policy, str) or not policy.strip():
        raise _config_error("invalid_policy_snapshot")
    if not isinstance(flags, Mapping) or any(
        not isinstance(key, str) or type(item) is not bool
        for key, item in flags.items()
    ):
        raise _config_error("invalid_feature_flags")
    return AgentConfig(
        schema_version=1,
        default_persona_id=persona.strip(),
        policy_snapshot_id=policy.strip(),
        feature_flags=MappingProxyType(dict(flags)),
    )


def _config_error(code: str, *reason_codes: str) -> ConfigError:
    return ConfigError(
        ErrorInfo(
            schema_version=1,
            code=code,
            category=ErrorCategory.VALIDATION,
            retryable=False,
            outcome_unknown=False,
            public_message_key="config.invalid",
            reason_codes=reason_codes,
        )
    )
