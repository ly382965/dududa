from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import (
    Actor,
    ActorRef,
    ConversationScope,
    ResolvedIdentityRef,
)
from dududa.domain.message import MessageEnvelope, MessageReference
from dududa.domain.primitives import ComponentRevision, ConversationType, PrivacyLevel
from dududa.errors import validation_error
from dududa.perception.contracts import (
    PerceptionContext,
    PerceptionIdentity,
    PerceptionLimits,
    PerceptionMessage,
)
from dududa.security.digests import actor_digest, scope_digest

from .contracts import (
    CurrentMessageContext,
    OfflinePreprocessReceipt,
    RuntimeAdmissionAction,
    RuntimeIdentityBinding,
)
from .perception import serialize_perception_context

CAPABILITY_CATEGORY_FEATURE_PREFIX = "capability.category."


@dataclass(frozen=True, slots=True)
class CurrentMessageContextBuilderConfig:
    schema_version: int
    limits: PerceptionLimits
    maximum_content_input_tokens: int
    private_data_classification: PrivacyLevel
    group_data_classification: PrivacyLevel
    component_revision: ComponentRevision
    available_capability_categories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.limits, PerceptionLimits):
            raise validation_error("invalid_context_perception_limits")
        if (
            type(self.maximum_content_input_tokens) is not int
            or self.maximum_content_input_tokens < 1
        ):
            raise validation_error("invalid_context_token_limit")
        for name in (
            "private_data_classification",
            "group_data_classification",
        ):
            value = getattr(self, name)
            if not isinstance(value, PrivacyLevel) or value is PrivacyLevel.RESTRICTED:
                raise validation_error("invalid_context_data_classification", name)
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_context_builder_revision")
        categories = tuple(self.available_capability_categories)
        if (
            len(categories) > self.limits.max_capability_categories
            or len(categories) != len(set(categories))
            or any(
                not isinstance(value, str) or not value.strip() for value in categories
            )
        ):
            raise validation_error("invalid_context_capability_categories")
        object.__setattr__(
            self,
            "available_capability_categories",
            tuple(sorted(categories)),
        )


class CurrentMessageContextBuilder:
    def __init__(self, config: CurrentMessageContextBuilderConfig) -> None:
        if not isinstance(config, CurrentMessageContextBuilderConfig):
            raise TypeError("invalid Current Message Context Builder config")
        self._config = config

    @property
    def config(self) -> CurrentMessageContextBuilderConfig:
        return self._config

    def preprocess(
        self,
        message: MessageEnvelope,
        actor: Actor,
        *,
        feature_flags: Mapping[str, bool] | None = None,
    ) -> OfflinePreprocessReceipt:
        if not isinstance(message, MessageEnvelope) or not isinstance(actor, Actor):
            raise validation_error("invalid_context_builder_input")
        if (
            actor.platform != message.platform
            or actor.bot_id != message.bot_id
            or actor.user_id != message.user_id
        ):
            raise validation_error("context_builder_identity_mismatch")
        classification = self._classification(message.conversation_type)
        explicit = message.conversation_type is ConversationType.PRIVATE or any(
            mention.platform == message.platform and mention.user_id == message.bot_id
            for mention in message.mentions
        )
        proactive = bool(
            feature_flags and feature_flags.get("proactive_group_participation", False)
        )
        if actor.user_id == message.bot_id:
            action = RuntimeAdmissionAction.IGNORE
            reasons = ("self_message",)
        elif message.attachments:
            action = RuntimeAdmissionAction.DEFER
            reasons = ("attachments_disabled",)
        elif not message.text.strip():
            action = RuntimeAdmissionAction.IGNORE
            reasons = ("empty_text_message",)
        elif message.conversation_type is ConversationType.CHANNEL:
            action = RuntimeAdmissionAction.IGNORE
            reasons = ("channel_out_of_scope",)
        elif (
            message.conversation_type is ConversationType.GROUP
            and not explicit
            and not proactive
        ):
            action = RuntimeAdmissionAction.IGNORE
            reasons = ("group_explicit_mention_required",)
        else:
            action = RuntimeAdmissionAction.PROCEED
            reasons = (
                ("proactive_group_text_admitted",)
                if proactive and not explicit
                else ("s10_text_admitted",)
            )
        return OfflinePreprocessReceipt(
            schema_version=1,
            message_digest=canonical_digest(
                message,
                domain="runtime:admission-message:v1",
            ),
            actor_digest=actor_digest(actor),
            action=action,
            data_classification=classification,
            explicit_interaction=explicit,
            reason_codes=reasons,
            component_revision=self._config.component_revision,
        )

    def build(
        self,
        message: MessageEnvelope,
        actor: Actor,
        scope: ConversationScope,
        preprocess: OfflinePreprocessReceipt,
        *,
        feature_flags: Mapping[str, bool] | None = None,
    ) -> CurrentMessageContext:
        if not isinstance(preprocess, OfflinePreprocessReceipt):
            raise validation_error("invalid_preprocess_receipt")
        if preprocess.action is not RuntimeAdmissionAction.PROCEED:
            raise validation_error("context_build_not_admitted")
        if (
            scope.platform != message.platform
            or scope.bot_id != message.bot_id
            or scope.conversation_type is not message.conversation_type
            or scope.conversation_id != message.conversation_id
            or scope.group_id != message.group_id
        ):
            raise validation_error("context_builder_scope_mismatch")
        if (
            actor.platform != message.platform
            or actor.bot_id != message.bot_id
            or actor.user_id != message.user_id
        ):
            raise validation_error("context_builder_identity_mismatch")

        scope_hash = scope_digest(scope)
        raw_identity_ids = {message.bot_id, message.user_id}
        raw_identity_ids.update(mention.user_id for mention in message.mentions)
        reference_by_raw = {
            message.bot_id: "identity:bot",
            message.user_id: "identity:author",
        }
        mention_ids = sorted(
            raw_id
            for raw_id in raw_identity_ids
            if raw_id not in {message.bot_id, message.user_id}
        )
        reference_by_raw.update(
            {
                raw_id: f"identity:mention:{index}"
                for index, raw_id in enumerate(mention_ids, start=1)
            }
        )
        identities = tuple(
            PerceptionIdentity(
                schema_version=1,
                identity_ref=reference_by_raw[raw_id],
                is_bot=raw_id == message.bot_id,
            )
            for raw_id in sorted(raw_identity_ids)
        )
        current_message_ref = "message:current"
        perception_message = PerceptionMessage(
            schema_version=1,
            message_ref=current_message_ref,
            author_identity_ref=reference_by_raw[message.user_id],
            text=message.text,
            reply_to_message_ref=None,
            mentioned_identity_refs=tuple(
                reference_by_raw[mention.user_id] for mention in message.mentions
            ),
            is_bot_authored=False,
        )
        available_categories = self._config.available_capability_categories
        if feature_flags is not None:
            available_categories = tuple(
                category
                for category in available_categories
                if feature_flags.get(
                    f"{CAPABILITY_CATEGORY_FEATURE_PREFIX}{category}",
                    True,
                )
            )
        perception = PerceptionContext(
            schema_version=1,
            context_id=str(
                canonical_digest(
                    {
                        "scope_digest": scope_hash,
                        "message_id": message.message_id,
                    },
                    domain="runtime:perception-context-id:v1",
                )
            ),
            scope_digest=scope_hash,
            conversation_type=message.conversation_type,
            identities=identities,
            messages=(perception_message,),
            current_message_ref=current_message_ref,
            bot_identity_ref=reference_by_raw[message.bot_id],
            limits=self._config.limits,
            available_capability_categories=available_categories,
            degraded_components=(),
            content_input_tokens_upper_bound=1,
            data_classification=preprocess.data_classification,
        )
        token_bound = max(1, len(serialize_perception_context(perception)))
        if token_bound > self._config.maximum_content_input_tokens:
            raise validation_error("current_message_context_token_limit_exceeded")
        perception = replace(
            perception,
            content_input_tokens_upper_bound=token_bound,
        )
        bindings = tuple(
            RuntimeIdentityBinding(
                schema_version=1,
                identity_ref=reference_by_raw[raw_id],
                resolved=ResolvedIdentityRef(
                    identity_ref=reference_by_raw[raw_id],
                    actor_ref=ActorRef(
                        platform=message.platform,
                        bot_id=message.bot_id,
                        opaque_actor_id=raw_id,
                    ),
                    evidence_message_ids=(message.message_id,),
                ),
            )
            for raw_id in sorted(raw_identity_ids)
            if raw_id != message.bot_id
        )
        return CurrentMessageContext(
            schema_version=1,
            perception=perception,
            identity_bindings=bindings,
            current_author_identity_ref=reference_by_raw[message.user_id],
            current_message_reference=MessageReference(
                platform=message.platform,
                bot_id=message.bot_id,
                conversation_id=message.conversation_id,
                message_id=message.message_id,
            ),
            builder_revision=self._config.component_revision,
        )

    def _classification(self, value: ConversationType) -> PrivacyLevel:
        if value is ConversationType.PRIVATE:
            return self._config.private_data_classification
        return self._config.group_data_classification
