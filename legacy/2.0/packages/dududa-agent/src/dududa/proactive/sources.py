from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from dududa.contracts.canonical import canonical_digest, canonical_json_bytes
from dududa.domain.content import Citation
from dududa.errors import DududaError, ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext

from .contracts import SourceBatch, SourceFailure, SourceItem
from .digests import (
    source_item_revision_content_digest,
    source_item_revision_key,
    source_item_stable_key,
)
from .source_contracts import (
    SourceCapabilityObservation,
    SourceCursor,
    SourceDefinition,
    SourceFetchReceipt,
    SourceFetchRequest,
    SourceFetchStatus,
    SourceIdentityRule,
    SourceItemIdentity,
    SourcePolicySnapshot,
    SourceProvenance,
    SourceStateCommitPlan,
    SourceStateCommitReceipt,
    SourceStateMutation,
)

if TYPE_CHECKING:
    from dududa.ports.proactive import (
        SourceCapabilityReader,
        SourcePolicyRegistry,
        SourceStateStore,
    )

_ARXIV_ID = re.compile(r"(?P<base>[0-9]{4}\.[0-9]{4,5})(?:v[1-9][0-9]*)?")
_PROMPT_PATTERN = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous|system\s+prompt|developer\s+message|"
    r"assistant\s*:|<\s*/?\s*(?:script|style|iframe|html|body|[a-z][a-z0-9-]*\b))",
    re.IGNORECASE,
)
_ITEM_KEYS = {
    "external_id",
    "title",
    "summary",
    "canonical_url",
    "published_at",
    "source_revision",
}


@dataclass(frozen=True, slots=True)
class _PreparedSource:
    definition: SourceDefinition
    current_cursor: SourceCursor | None
    observation: SourceCapabilityObservation
    items: tuple[SourceItem, ...]
    identities: tuple[SourceItemIdentity, ...]
    provenance: SourceProvenance


class GovernedSourceProvider:
    """Normalizes fixed public Capability observations into source receipts."""

    def __init__(
        self,
        policy_registry: SourcePolicyRegistry,
        reader: SourceCapabilityReader,
        state_store: SourceStateStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from dududa.ports.proactive import (
            SourceCapabilityReader,
            SourcePolicyRegistry,
            SourceStateStore,
        )

        for value, expected, name in (
            (policy_registry, SourcePolicyRegistry, "policy_registry"),
            (reader, SourceCapabilityReader, "reader"),
            (state_store, SourceStateStore, "state_store"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"{name} does not implement its source Port")
        self._policy_registry = policy_registry
        self._reader = reader
        self._state_store = state_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()

    async def fetch(
        self,
        request: SourceFetchRequest,
        *,
        call: PortCallContext,
    ) -> SourceFetchReceipt:
        if not isinstance(request, SourceFetchRequest):
            raise validation_error("invalid_source_fetch_request")
        now = _utc(self._clock(), "source_provider_now")
        try:
            _validate_call(call, now)
        except DududaError as exc:
            if exc.info.category is ErrorCategory.CANCELLED:
                return _cancelled(request, now, exc.info.code)
            raise
        if request.requested_at > now:
            raise validation_error("source_request_from_future")
        acquired = False
        try:
            await _bounded_await(
                self._lock.acquire(),
                call=call,
                now=now,
                code="source_provider_lock",
            )
            acquired = True
            return await self._fetch(
                request,
                call=call,
                now=_utc(self._clock(), "source_provider_now"),
            )
        except DududaError as exc:
            if exc.info.category is ErrorCategory.CANCELLED:
                return _cancelled(
                    request,
                    _utc(self._clock(), "source_provider_now"),
                    exc.info.code,
                )
            raise
        finally:
            if acquired:
                self._lock.release()

    async def _fetch(
        self,
        request: SourceFetchRequest,
        *,
        call: PortCallContext,
        now: datetime,
    ) -> SourceFetchReceipt:
        policy = self._policy_registry.resolve(
            request.source_policy_id,
            expected_digest=request.source_policy_digest,
        )
        definitions = self._definitions(policy, request)
        failures: list[SourceFailure] = []
        prepared: list[_PreparedSource] = []
        candidate_count = 0

        for definition in definitions:
            try:
                _validate_call(call, _utc(self._clock(), "source_provider_now"))
                current_cursor = await _bounded_await(
                    self._state_store.load_cursor(
                        request.subscription_id,
                        definition.source_id,
                        call=call,
                    ),
                    call=call,
                    now=_utc(self._clock(), "source_provider_now"),
                    code="source_cursor_load",
                )
                observation = await _bounded_await(
                    self._reader.read(
                        definition,
                        current_cursor,
                        request,
                        call=call,
                    ),
                    call=call,
                    now=_utc(self._clock(), "source_provider_now"),
                    code="source_reader",
                )
                received_at = _utc(self._clock(), "source_provider_now")
                source_items, source_identities, source_provenance = _normalize(
                    observation,
                    definition,
                    policy,
                    request,
                    received_at,
                )
                if candidate_count + len(source_items) > request.maximum_items:
                    raise validation_error("source_batch_capacity_exceeded")
            except DududaError as exc:
                if exc.info.category is ErrorCategory.CANCELLED:
                    return _cancelled(
                        request,
                        _utc(self._clock(), "source_provider_now"),
                        exc.info.code,
                    )
                failures.append(
                    SourceFailure(
                        definition.source_id,
                        exc.info.code,
                        exc.info.retryable,
                    )
                )
                continue
            except Exception:  # noqa: BLE001 - raw Provider details stay private.
                failures.append(
                    SourceFailure(
                        definition.source_id,
                        "source_reader_failed",
                        False,
                    )
                )
                continue

            candidate_count += len(source_items)
            prepared.append(
                _PreparedSource(
                    definition,
                    current_cursor,
                    observation,
                    source_items,
                    source_identities,
                    source_provenance,
                )
            )

        if not prepared:
            return SourceFetchReceipt(
                schema_version=1,
                request_digest=request.request_digest,
                status=SourceFetchStatus.FAILED,
                batch=None,
                failures=tuple(sorted(failures, key=lambda item: item.source_id)),
                provenance=(),
                identities=(),
                dedup_receipts=(),
                next_cursors=(),
                reason_codes=("all_sources_failed",),
                completed_at=_utc(self._clock(), "source_provider_now"),
            )

        try:
            _validate_call(call, _utc(self._clock(), "source_provider_now"))
        except DududaError as exc:
            if exc.info.category is ErrorCategory.CANCELLED:
                return _cancelled(
                    request,
                    _utc(self._clock(), "source_provider_now"),
                    exc.info.code,
                )
            raise

        planned_at = _utc(self._clock(), "source_provider_now")
        plan = SourceStateCommitPlan(
            schema_version=1,
            request_digest=request.request_digest,
            subscription_id=request.subscription_id,
            mutations=tuple(
                SourceStateMutation(
                    schema_version=1,
                    subscription_id=request.subscription_id,
                    source_id=staged.definition.source_id,
                    expected_cursor_digest=(
                        staged.current_cursor.cursor_digest
                        if staged.current_cursor is not None
                        else None
                    ),
                    next_cursor=_next_cursor(
                        request,
                        staged.observation,
                        staged.current_cursor,
                    ),
                    identities=staged.identities,
                    notify_revisions=staged.definition.notify_revisions,
                    observed_at=staged.observation.observed_at,
                )
                for staged in prepared
            ),
            planned_at=planned_at,
        )
        state_receipt = None
        try:
            state_receipt = await _bounded_await(
                self._state_store.commit_fetch(plan, call=call),
                call=call,
                now=_utc(self._clock(), "source_provider_now"),
                code="source_state_commit",
            )
            if not isinstance(state_receipt, SourceStateCommitReceipt):
                raise validation_error("invalid_source_state_commit_receipt")
        except DududaError as exc:
            if exc.info.category is ErrorCategory.CANCELLED:
                return _cancelled(
                    request,
                    _utc(self._clock(), "source_provider_now"),
                    exc.info.code,
                )
            failures.extend(
                SourceFailure(
                    staged.definition.source_id,
                    exc.info.code,
                    exc.info.retryable,
                )
                for staged in prepared
            )
        except Exception:  # noqa: BLE001 - state details stay private.
            failures.extend(
                SourceFailure(
                    staged.definition.source_id,
                    "source_state_commit_failed",
                    False,
                )
                for staged in prepared
            )
        else:
            succeeded = [staged.definition.source_id for staged in prepared]
            provenance = [staged.provenance for staged in prepared]
            identities = [
                identity for staged in prepared for identity in staged.identities
            ]
            receipts = list(state_receipt.dedup_receipts)
            cursors = list(state_receipt.next_cursors)
            all_items = [item for staged in prepared for item in staged.items]
            emitted = [
                item
                for item, receipt in zip(all_items, receipts, strict=True)
                if receipt.should_emit
            ]

        if state_receipt is None:
            return SourceFetchReceipt(
                schema_version=1,
                request_digest=request.request_digest,
                status=SourceFetchStatus.FAILED,
                batch=None,
                failures=tuple(sorted(failures, key=lambda item: item.source_id)),
                provenance=(),
                identities=(),
                dedup_receipts=(),
                next_cursors=(),
                reason_codes=("all_sources_failed",),
                completed_at=_utc(self._clock(), "source_provider_now"),
            )

        completed_at = _utc(self._clock(), "source_provider_now")
        source_snapshot_revision = _snapshot_revision(provenance, cursors)
        batch = SourceBatch(
            schema_version=1,
            batch_id=f"batch-{request.request_id}",
            items=tuple(emitted),
            succeeded_sources=tuple(sorted(succeeded)),
            failed_sources=tuple(sorted(failures, key=lambda item: item.source_id)),
            source_snapshot_revision=source_snapshot_revision,
            observed_at=completed_at,
        )
        if failures:
            status = SourceFetchStatus.PARTIAL
        elif not emitted:
            status = SourceFetchStatus.NO_NEW_ITEMS
        else:
            status = SourceFetchStatus.SUCCEEDED
        return SourceFetchReceipt(
            schema_version=1,
            request_digest=request.request_digest,
            status=status,
            batch=batch,
            failures=tuple(sorted(failures, key=lambda item: item.source_id)),
            provenance=tuple(provenance),
            identities=tuple(identities),
            dedup_receipts=tuple(receipts),
            next_cursors=tuple(cursors),
            reason_codes=(status.value,),
            completed_at=completed_at,
        )

    @staticmethod
    def _definitions(
        policy: SourcePolicySnapshot,
        request: SourceFetchRequest,
    ) -> tuple[SourceDefinition, ...]:
        definitions = tuple(
            policy.definition(source_id) for source_id in request.source_ids
        )
        if any(
            definition.category not in request.categories for definition in definitions
        ):
            raise validation_error("source_request_category_mismatch")
        return definitions


def _normalize(
    observation: SourceCapabilityObservation,
    definition: SourceDefinition,
    policy: SourcePolicySnapshot,
    request: SourceFetchRequest,
    received_at: datetime,
) -> tuple[tuple[SourceItem, ...], tuple[SourceItemIdentity, ...], SourceProvenance]:
    _validate_observation(observation, definition)
    maximum_age = min(definition.maximum_age, request.maximum_age)
    if not received_at - maximum_age <= observation.observed_at <= received_at:
        raise validation_error("source_observation_not_fresh")
    if len(canonical_json_bytes(observation.data)) > definition.maximum_payload_bytes:
        raise validation_error("source_observation_too_large")
    if set(observation.data) != {"schema_version", "items"}:
        raise validation_error("source_observation_schema_drift")
    if (
        type(observation.data["schema_version"]) is not int
        or observation.data["schema_version"] != 1
    ):
        raise validation_error("unsupported_source_observation_schema")
    raw_items = observation.data["items"]
    if (
        not isinstance(raw_items, (tuple, list))
        or len(raw_items) > definition.maximum_items
    ):
        raise validation_error("invalid_source_observation_items")

    items: list[SourceItem] = []
    identities: list[SourceItemIdentity] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items):
        item = _normalize_item(
            raw,
            definition,
            received_at,
            maximum_age,
            index,
        )
        identity = _identity(item, definition)
        stable = str(identity.stable_key_digest)
        if stable in seen:
            raise validation_error("duplicate_source_item_identity")
        seen.add(stable)
        items.append(item)
        identities.append(identity)

    ordered = sorted(
        zip(items, identities, strict=True), key=lambda pair: _item_sort_key(pair[0])
    )
    items = [item for item, _ in ordered]
    identities = [identity for _, identity in ordered]

    provenance = SourceProvenance(
        schema_version=1,
        source_id=observation.source_id,
        capability_id=observation.capability_id,
        capability_definition_digest=observation.capability_definition_digest,
        provider_id=observation.provider_id,
        provider_generation=observation.provider_generation,
        provider_result_digest=observation.provider_result_digest,
        policy_digest=policy.policy_digest,
        schema_revision=observation.schema_revision,
        result_mapping_revision=observation.result_mapping_revision,
        observed_at=observation.observed_at,
    )
    return tuple(items), tuple(identities), provenance


def _validate_observation(
    observation: SourceCapabilityObservation,
    definition: SourceDefinition,
) -> None:
    if not isinstance(observation, SourceCapabilityObservation):
        raise validation_error("invalid_source_capability_observation")
    if (
        observation.source_id != definition.source_id
        or observation.capability_id != definition.capability_id
        or observation.capability_definition_digest
        != definition.capability_definition_digest
        or observation.schema_revision != definition.schema_revision
        or observation.result_mapping_revision != definition.result_mapping_revision
    ):
        raise validation_error("source_capability_binding_mismatch")


def _normalize_item(
    raw: object,
    definition: SourceDefinition,
    observed_at: datetime,
    maximum_age: timedelta,
    index: int,
) -> SourceItem:
    if not isinstance(raw, Mapping) or set(raw) != _ITEM_KEYS:
        raise validation_error("source_item_schema_drift")
    external_id = raw["external_id"]
    if external_id is not None and (
        not isinstance(external_id, str) or not external_id.strip()
    ):
        raise validation_error("invalid_source_external_id")
    title = _plain_text(raw["title"], "source_title", maximum=512)
    summary = _plain_text(raw["summary"], "source_summary", maximum=8_192)
    canonical_url = _canonical_url(raw["canonical_url"], definition)
    published_at = _optional_datetime(raw["published_at"], "source_published_at")
    if definition.require_published_at and published_at is None:
        raise validation_error("source_published_at_required")
    if published_at is not None and (
        published_at > observed_at or published_at < observed_at - maximum_age
    ):
        raise validation_error("source_item_not_fresh")
    source_revision = raw["source_revision"]
    if not isinstance(source_revision, str) or not source_revision.strip():
        raise validation_error("invalid_source_item_revision")
    item = SourceItem(
        schema_version=1,
        source_id=definition.source_id,
        external_id=external_id,
        category=definition.category,
        title=title,
        summary=summary,
        canonical_url=canonical_url,
        published_at=published_at,
        observed_at=observed_at,
        source_revision=source_revision,
        citations=(
            Citation(
                f"source-{definition.source_id}-{index + 1}",
                title,
                canonical_url,
            ),
        ),
        warnings=("source_observation_untrusted",),
    )
    return item


def _identity(item: SourceItem, definition: SourceDefinition) -> SourceItemIdentity:
    if definition.identity_rule is SourceIdentityRule.EXTERNAL_ID:
        if item.external_id is None:
            raise validation_error("source_external_id_required")
        external_identity = item.external_id
    elif definition.identity_rule is SourceIdentityRule.ARXIV_BASE_ID:
        if item.external_id is None:
            raise validation_error("source_external_id_required")
        match = _ARXIV_ID.fullmatch(item.external_id)
        if match is None:
            raise validation_error("invalid_arxiv_source_identity")
        external_identity = match.group("base")
        if urlsplit(item.canonical_url).path != f"/abs/{item.external_id}":
            raise validation_error("arxiv_identity_url_mismatch")
    else:
        external_identity = item.canonical_url
    stable = source_item_stable_key(definition.source_id, external_identity)
    revision_content = source_item_revision_content_digest(item)
    revision = source_item_revision_key(
        stable,
        item.source_revision,
        revision_content,
    )
    return SourceItemIdentity(
        schema_version=1,
        source_id=definition.source_id,
        external_identity=external_identity,
        stable_key_digest=stable,
        revision_key_digest=revision,
        revision_content_digest=revision_content,
        content_digest=item.content_digest,
        identity_rule_revision=definition.definition_revision,
    )


def _next_cursor(
    request: SourceFetchRequest,
    observation: SourceCapabilityObservation,
    current: SourceCursor | None,
) -> SourceCursor:
    if current is not None and (
        current.token == observation.next_cursor_token
        and current.source_snapshot_revision == observation.source_snapshot_revision
    ):
        return current
    return SourceCursor(
        schema_version=1,
        subscription_id=request.subscription_id,
        source_id=observation.source_id,
        token=observation.next_cursor_token,
        source_snapshot_revision=observation.source_snapshot_revision,
        revision=current.revision + 1 if current is not None else 1,
        observed_at=observation.observed_at,
    )


def _canonical_url(value: object, definition: SourceDefinition) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 2_048:
        raise validation_error("invalid_source_url")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname.lower() if parsed.hostname is not None else None
        port = parsed.port
    except ValueError:
        raise validation_error("invalid_source_url") from None
    path = parsed.path or "/"
    if (
        parsed.scheme != "https"
        or host not in definition.allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or port not in {None, 443}
        or "%" in path
        or "\\" in path
        or "//" in path
        or any(segment in {".", ".."} for segment in path.split("/"))
        or not any(
            _path_is_allowed(path, prefix)
            for prefix in definition.allowed_path_prefixes
        )
    ):
        raise validation_error("source_url_not_allowlisted")
    return urlunsplit(("https", host, path, "", ""))


def _path_is_allowed(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/") or "/"
    return normalized == "/" or path == normalized or path.startswith(f"{normalized}/")


def _plain_text(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_source_text", field_name)
    normalized = " ".join(value.split())
    if len(normalized.encode("utf-8")) > maximum:
        raise validation_error("source_text_too_large", field_name)
    if _PROMPT_PATTERN.search(normalized):
        raise validation_error("source_prompt_injection_detected")
    return normalized


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise validation_error("invalid_source_datetime", field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise validation_error("invalid_source_datetime", field_name) from None
    return _utc(parsed, field_name)


def _snapshot_revision(
    provenance: Sequence[SourceProvenance],
    cursors: Sequence[SourceCursor],
) -> str:
    digest = str(
        canonical_digest(
            {
                "provenance": tuple(item.provenance_digest for item in provenance),
                "cursors": tuple(item.cursor_digest for item in cursors),
            },
            domain="proactive:source-snapshot-revision:v1",
        )
    )
    return f"snapshot-{digest.rsplit(':', 1)[-1]}"


def _item_sort_key(item: SourceItem) -> tuple:
    return (
        item.category.value,
        -(item.published_at or item.observed_at).timestamp(),
        item.source_id,
        item.external_id or item.canonical_url,
    )


def _cancelled(
    request: SourceFetchRequest,
    now: datetime,
    reason: str,
) -> SourceFetchReceipt:
    return SourceFetchReceipt(
        schema_version=1,
        request_digest=request.request_digest,
        status=SourceFetchStatus.CANCELLED,
        batch=None,
        failures=(),
        provenance=(),
        identities=(),
        dedup_receipts=(),
        next_cursors=(),
        reason_codes=(reason,),
        completed_at=now,
    )


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_source_port_call")
    if call.cancellation.is_cancelled:
        raise error(
            "source_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= now:
        raise error(
            "source_call_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


async def _bounded_await(
    awaitable,
    *,
    call: PortCallContext,
    now: datetime,
    code: str,
):
    remaining = (call.deadline - now).total_seconds()
    if remaining <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise error(
            f"{code}_timeout",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )
    operation = asyncio.create_task(awaitable)
    cancellation = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (operation, cancellation),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation in done:
            operation.cancel()
            raise error(
                f"{code}_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if operation not in done:
            operation.cancel()
            raise error(
                f"{code}_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
        return operation.result()
    finally:
        for task in (operation, cancellation):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation, cancellation, return_exceptions=True)


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_source_datetime", field_name)
    return value.astimezone(timezone.utc)


__all__ = ["GovernedSourceProvider"]
