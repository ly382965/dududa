from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ConversationType, DigestString
from dududa.errors import validation_error
from dududa.runtime.state import ConnectorResult

from .contracts import (
    RolloutAdmissionAction,
    RolloutAdmissionDecision,
    RolloutControlConfig,
    RolloutMode,
)


def rollout_message_key_digest(connector: ConnectorResult) -> DigestString:
    if not isinstance(connector, ConnectorResult):
        raise validation_error("invalid_rollout_connector_result")
    return canonical_digest(
        connector.message.dedup_key,
        domain="rollout:message-dedup-key:v1",
    )


def decide_rollout_admission(
    connector: ConnectorResult,
    config: RolloutControlConfig,
) -> RolloutAdmissionDecision:
    if not isinstance(connector, ConnectorResult):
        raise validation_error("invalid_rollout_connector_result")
    if not isinstance(config, RolloutControlConfig):
        raise validation_error("invalid_rollout_config")
    message = connector.message
    digest = rollout_message_key_digest(connector)
    if config.mode is RolloutMode.OFF:
        return _legacy(config, digest, "rollout_off")
    if config.kill_switch:
        return _legacy(config, digest, "kill_switch_active")
    if message.conversation_type is not ConversationType.GROUP or not message.group_id:
        return _legacy(config, digest, "group_required")
    if (
        "*" not in config.allowlisted_group_ids
        and message.group_id not in config.allowlisted_group_ids
    ):
        return _legacy(config, digest, "group_not_allowlisted")
    if connector.actor.user_id == message.bot_id:
        return _legacy(config, digest, "self_message")
    if not any(
        mention.platform == message.platform and mention.user_id == message.bot_id
        for mention in message.mentions
    ):
        return _legacy(config, digest, "trusted_explicit_mention_required")
    normalized = message.text.strip()
    if not normalized:
        return _legacy(config, digest, "supported_text_required")
    if len(normalized.encode("utf-8")) > config.maximum_text_bytes:
        return _legacy(config, digest, "text_limit_exceeded")
    if message.attachments:
        return _legacy(config, digest, "attachments_not_supported")
    if config.memory_enabled:
        return _legacy(config, digest, "memory_must_be_disabled")
    if config.mode is RolloutMode.SHADOW:
        return RolloutAdmissionDecision(
            1,
            RolloutAdmissionAction.SHADOW,
            config.revision,
            digest,
            ("shadow_admitted",),
        )
    if config.mode is not RolloutMode.CANARY:
        raise validation_error("invalid_rollout_mode")
    if not config.delivery_enabled:
        return _legacy(config, digest, "delivery_disabled")
    return RolloutAdmissionDecision(
        1,
        RolloutAdmissionAction.CANARY,
        config.revision,
        digest,
        ("canary_admitted",),
    )


def _legacy(
    config: RolloutControlConfig,
    digest: DigestString,
    reason: str,
) -> RolloutAdmissionDecision:
    return RolloutAdmissionDecision(
        1,
        RolloutAdmissionAction.LEGACY,
        config.revision,
        digest,
        (reason,),
    )
