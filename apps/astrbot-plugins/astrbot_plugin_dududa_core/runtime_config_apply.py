"""Narrow authenticated API for external pools; owns only Dududa generations.

No Docker, subprocess, global Provider reload, or client supplied paths. All
credentials remain at this host boundary. The Web submits a revision only.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from .adapters.api_key_pools import load_api_key_pool_snapshot
from .adapters.deepseek_config import build_candidate
from .adapters.model_evidence import _parse_evidence
from .config import ASTRBOT_CONFIG_PATH, PLUGIN_CONFIG_PATH


class RuntimeApplyError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError("configuration_not_object")
    return value


def _write_private(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".dududa-apply-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _target_rows(command: dict, snapshot) -> dict:
    ids = {p.provider_id for p in snapshot.pools}
    sources = {p.source_id for p in snapshot.pools}
    return {
        "provider": [p for p in command.get("provider", []) if p.get("id") in ids],
        "provider_sources": [
            p for p in command.get("provider_sources", []) if p.get("id") in sources
        ],
    }


def _model_rows(core: dict) -> object:
    return json.loads(core.get("runtime_models_json", "[]"))


def _sync_host_configuration(command: dict, snapshot) -> None:
    from astrbot.core import astrbot_config

    # Synchronize the host's configuration cache, not its Provider instances.
    # Otherwise a later ordinary Dashboard save could restore stale credentials.
    for key, wanted in _target_rows(command, snapshot).items():
        replacements = {row["id"]: row for row in wanted}
        current = astrbot_config.get(key, [])
        existing = {row["id"] for row in current}
        astrbot_config[key] = [replacements.get(row["id"], row) for row in current]
        astrbot_config[key].extend(row for row in wanted if row["id"] not in existing)


class _ProviderContext:
    def __init__(self, original, providers, evidence):
        self.original, self.providers, self.evidence = original, providers, evidence

    def get_provider_by_id(self, provider_id):
        return self.providers.get(provider_id) or self.original.get_provider_by_id(
            provider_id
        )

    def resolve_dududa_model_provider_evidence(self, provider_id, descriptor):
        return self.evidence.get(provider_id)

    def __getattr__(self, name):
        return getattr(self.original, name)


async def _close_providers(providers: dict) -> None:
    for provider in providers.values():
        await provider.client.close()


def _host_evidence(document: dict, snapshot) -> dict:
    """Reuse only evidence of this installed, bounded OpenAI host implementation."""
    from astrbot import __version__
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    query = inspect.getsource(ProviderOpenAIOfficial._query)
    chat = inspect.getsource(ProviderOpenAIOfficial.text_chat)
    if (
        "with_options(max_retries=0)" not in query
        or "request_max_retries <= 1" not in chat
    ):
        raise RuntimeApplyError("bounded_host_adapter_required", 422)
    result = {}
    for pool in snapshot.pools:
        previous = next(
            (
                row
                for row in document.get("providers", [])
                if row.get("astrbot_provider_id") == pool.provider_id
            ),
            None,
        )
        if not previous or previous.get("host_version") != __version__:
            raise RuntimeApplyError("current_host_evidence_required", 422)
        evidence = _parse_evidence(previous, 0)
        if not all(
            (
                evidence.single_request_verified,
                evidence.model_binding_verified,
                evidence.output_limit_verified,
                evidence.residency_verified,
                evidence.retention_verified,
                evidence.sanitized_logging_verified,
                evidence.deadline_enforcement_verified,
                evidence.cancellation_enforcement_verified,
            )
        ):
            raise RuntimeApplyError("current_host_evidence_required", 422)
        if (
            "CN" not in previous["verified_data_residencies"]
            or "provider_managed" not in previous["verified_retention_modes"]
        ):
            raise RuntimeApplyError("provider_policy_evidence_required", 422)
        result[pool.provider_id] = copy.deepcopy(previous)
    return result


async def _prepare(plugin, command, core, snapshot, evidence_document):
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    from .composition import (
        _default_runtime_budget,
        build_production_runtime,
        install_production_runtime,
    )

    evidence_rows = _host_evidence(evidence_document, snapshot)
    providers = {}
    candidate = copy.copy(plugin)
    candidate.config = core
    candidate.rollout_bridge = candidate.runtime_assembly = None
    candidate._dududa_runtime_cleanup_assemblies = []
    try:
        for pool in snapshot.pools:
            source = next(
                row
                for row in command["provider_sources"]
                if row["id"] == pool.source_id
            )
            config = next(
                row for row in command["provider"] if row["id"] == pool.provider_id
            )
            provider = ProviderOpenAIOfficial(
                {**source, **config}, command.get("provider_settings", {})
            )
            providers[pool.provider_id] = provider
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt="Synthetic configuration check. Reply only OK.",
                    model=pool.model,
                    max_tokens=pool.max_output_tokens,
                    reasoning_effort=pool.reasoning_effort,
                    thinking={"type": "enabled"},
                    request_max_retries=1,
                ),
                timeout=min(pool.timeout_ms / 1000, 90),
            )
            if (
                getattr(response.raw_completion, "model", None) != pool.model
                or not response.completion_text.strip()
                or type(getattr(response.usage, "output", None)) is not int
                or not 0 < response.usage.output <= pool.max_output_tokens
            ):
                raise RuntimeApplyError("candidate_provider_probe_failed", 422)
            evidence_rows[pool.provider_id].update(
                verified_model_id=pool.model,
                verified_max_output_tokens=pool.max_output_tokens,
            )
            evidence_rows[pool.provider_id]["conformance_revision"][
                "config_revision"
            ] = f"external-pool-{snapshot.revision}"
        candidate.context = _ProviderContext(
            plugin.context,
            providers,
            {
                key: _parse_evidence(value, index)
                for index, (key, value) in enumerate(evidence_rows.items())
            },
        )
        assembly = build_production_runtime(candidate, core)
        candidate.runtime_assembly = assembly
        if (
            install_production_runtime(
                candidate,
                assembly,
                _default_runtime_budget(core),
                "production-shape-v1",
            )
            is None
        ):
            raise RuntimeApplyError("candidate_runtime_not_ready", 422)
        await assembly.refresh_model_health(
            timeout_seconds=20, evidence_ttl=timedelta(seconds=90)
        )
        # UNKNOWN health is not a usable route. The active probe cache contains
        # only accepted healthy/degraded evidence; require all three providers.
        if len(assembly._usable_model_health_evidence) != len(snapshot.pools):
            raise RuntimeApplyError("candidate_provider_health_failed", 422)
        retained = [
            row
            for row in evidence_document["providers"]
            if row["astrbot_provider_id"] not in providers
        ]
        return SimpleNamespace(
            plugin=candidate,
            providers=providers,
            evidence={
                **evidence_document,
                "providers": retained + list(evidence_rows.values()),
            },
        )
    except BaseException:
        if candidate.rollout_bridge is not None:
            await candidate.rollout_bridge.close()
        if candidate.runtime_assembly is not None:
            await candidate.runtime_assembly.close()
        await _close_providers(providers)
        raise


class RuntimeConfigApplyService:
    def __init__(
        self,
        plugin,
        *,
        snapshot_loader=load_api_key_pool_snapshot,
        prepare=_prepare,
        command_path=ASTRBOT_CONFIG_PATH,
        core_path=PLUGIN_CONFIG_PATH,
        writer=_write_private,
    ):
        self.plugin, self.snapshot_loader, self.prepare = (
            plugin,
            snapshot_loader,
            prepare,
        )
        self.command_path, self.core_path, self.writer = (
            Path(command_path),
            Path(core_path),
            writer,
        )
        self.lock = asyncio.Lock()
        self.providers = {}
        self.applied_command = None
        self.last_error = None
        self.closing = False
        self.pending_cleanup = []

    def status(self) -> dict:
        ready = bool(
            getattr(self.plugin.runtime_assembly, "ready", False)
            and self.plugin.rollout_bridge is not None
            and not getattr(self.plugin, "_dududa_runtime_terminated", False)
        )
        state, revision = "pending", None
        try:
            snapshot = self.snapshot_loader()
            revision = snapshot.revision
            command, core = _read(self.command_path), _read(self.core_path)
            expected_command, expected_core = build_candidate(
                command,
                core,
                snapshot,
                accept_retention=core.get("runtime_allow_provider_retention") is True,
            )
            applied_command = self.applied_command or command
            matches = _target_rows(expected_command, snapshot) == _target_rows(
                applied_command, snapshot
            ) and _model_rows(expected_core) == _model_rows(self.plugin.config)
            if matches and self.applied_command is None:
                for pool in snapshot.pools:
                    provider = self.plugin.context.get_provider_by_id(pool.provider_id)
                    source = next(
                        row
                        for row in expected_command["provider_sources"]
                        if row["id"] == pool.source_id
                    )
                    config = next(
                        row
                        for row in expected_command["provider"]
                        if row["id"] == pool.provider_id
                    )
                    live = getattr(provider, "provider_config", {})
                    if any(
                        live.get(key) != value
                        for key, value in {**source, **config}.items()
                    ):
                        matches = False
            if ready and matches and not self.closing:
                state = "applied"
        except Exception:  # noqa: BLE001 -- never disclose private configuration errors
            state = "unavailable" if revision is None else "pending"
        if self.lock.locked():
            state = "applying"
        return {
            "status": state,
            "savedRevision": revision,
            "ready": ready,
            "reason": self.last_error
            or (
                "runtime_configuration_current"
                if state == "applied"
                else "runtime_configuration_pending"
            ),
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "scope": "dududa_only",
            "cleanupPending": bool(self.pending_cleanup),
        }

    async def apply(self, expected_revision) -> dict:
        if self.closing:
            raise RuntimeApplyError("runtime_shutting_down")
        if self.lock.locked():
            raise RuntimeApplyError("runtime_apply_in_progress")
        async with self.lock:
            candidate = None
            old_bridge = self.plugin.rollout_bridge
            paused = False
            originals = {}
            written = []
            cache_touched = False
            try:
                snapshot = self.snapshot_loader()
                if snapshot.revision != expected_revision:
                    raise RuntimeApplyError("pool_revision_changed")
                proactive = getattr(self.plugin, "proactive_talk", None)
                if (
                    old_bridge is None
                    or getattr(old_bridge, "_active_configuration_calls", 0)
                    or old_bridge._shadow.active_count
                    or getattr(proactive, "_in_flight", None)
                ):
                    raise RuntimeApplyError("runtime_requests_active")
                command, core = _read(self.command_path), _read(self.core_path)
                evidence_path = Path(core["runtime_provider_evidence_path"])
                # Host configuration owns this path; the request never supplies it.
                if not evidence_path.is_absolute() or not evidence_path.is_relative_to(
                    self.command_path.parent
                ):
                    raise RuntimeApplyError("invalid_evidence_location", 422)
                evidence = _read(evidence_path)
                new_command, new_core = build_candidate(
                    command,
                    core,
                    snapshot,
                    accept_retention=core.get("runtime_allow_provider_retention")
                    is True,
                )
                candidate = await self.prepare(
                    self.plugin, new_command, new_core, snapshot, evidence
                )
                # Probes run while old Runtime is usable. No await between final
                # revision/active checks, private writes, and instance exchange.
                if self.snapshot_loader().revision != expected_revision:
                    raise RuntimeApplyError("pool_revision_changed")
                if self.closing or getattr(
                    self.plugin, "_dududa_runtime_terminated", False
                ):
                    raise RuntimeApplyError("runtime_shutting_down")
                originals = {
                    self.command_path: command,
                    self.core_path: core,
                    evidence_path: evidence,
                }
                if any(_read(path) != before for path, before in originals.items()):
                    raise RuntimeApplyError("host_configuration_changed")
                backup = (
                    self.command_path.parent / "private" / "dududa-runtime-last-good"
                )
                backup.mkdir(mode=0o700, parents=True, exist_ok=True)
                backup.chmod(0o700)
                for name, value in (
                    ("command", command),
                    ("core", core),
                    ("evidence", evidence),
                ):
                    _write_private(backup / f"{name}.json", value)
                if (
                    getattr(proactive, "_in_flight", None)
                    or not old_bridge.pause_configuration()
                ):
                    raise RuntimeApplyError("runtime_requests_active")
                paused = True
                for path, value in (
                    (self.command_path, new_command),
                    (self.core_path, new_core),
                    (evidence_path, candidate.evidence),
                ):
                    self.writer(path, value)
                    written.append(path)
                old_assembly, old_providers = (
                    self.plugin.runtime_assembly,
                    self.providers,
                )
                old_health = getattr(self.plugin, "_dududa_model_health_task", None)
                cache_touched = True
                _sync_host_configuration(new_command, snapshot)
                self.plugin.config.clear()
                self.plugin.config.update(new_core)
                self.plugin.runtime_assembly = candidate.plugin.runtime_assembly
                self.plugin.rollout_bridge = candidate.plugin.rollout_bridge
                if proactive is not None:
                    proactive._bridge = self.plugin.rollout_bridge
                self.plugin.proactive_talk = (
                    proactive or candidate.plugin.proactive_talk
                )
                self.providers = candidate.providers
                self.applied_command = new_command
                self.last_error = None
                candidate = None
            except BaseException as exc:
                rollback_failed = False
                if cache_touched:
                    try:
                        _sync_host_configuration(command, snapshot)
                    except Exception:  # noqa: BLE001 -- continue independent rollback steps
                        rollback_failed = True
                for path in reversed(written):
                    try:
                        self.writer(path, originals[path])
                    except Exception:  # noqa: BLE001 -- continue independent rollback steps
                        rollback_failed = True
                if paused:
                    old_bridge.resume_configuration()
                if candidate is not None:
                    await candidate.plugin.rollout_bridge.close()
                    await candidate.plugin.runtime_assembly.close()
                    await _close_providers(candidate.providers)
                self.last_error = (
                    "configuration_rollback_failed"
                    if rollback_failed
                    else exc.code
                    if isinstance(exc, RuntimeApplyError)
                    else "runtime_apply_failed"
                )
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise RuntimeApplyError(
                    self.last_error,
                    500
                    if rollback_failed
                    else exc.status
                    if isinstance(exc, RuntimeApplyError)
                    else 422,
                ) from None
            # Only now retire drained Dududa objects. Global AstrBot instances
            # are deliberately never reloaded/closed; their consumers are intact.
            self.pending_cleanup.extend(
                [
                    old_bridge,
                    old_assembly,
                    *(provider.client for provider in old_providers.values()),
                ]
            )
            retirement = asyncio.create_task(self._finish_swap(old_health))
            try:
                await asyncio.shield(retirement)
            except asyncio.CancelledError:
                # An HTTP disconnect cannot leave committed bindings without
                # their refresher or allow a second swap before retirement.
                await retirement
                raise
        return self.status()

    async def _finish_swap(self, old_health):
        if old_health is not None:
            old_health.cancel()
            await asyncio.gather(old_health, return_exceptions=True)
        self.plugin._dududa_model_health_task = None
        from .composition import _publish_runtime_status, _start_model_health_refresh

        _start_model_health_refresh(self.plugin)
        try:
            _publish_runtime_status(
                ready=True,
                state="ready",
                reason="runtime_ready",
                runtime_config=self.plugin.config,
            )
        except Exception:  # noqa: BLE001 -- legacy projection failure is not an apply failure
            # This legacy status projection is not the authority for live GET.
            self.last_error = "runtime_status_projection_failed"
        await self._cleanup()

    async def _cleanup(self):
        remaining = []
        for resource in self.pending_cleanup:
            try:
                await resource.close()
            except Exception:  # noqa: BLE001 -- retain failed resources for lifecycle retry
                remaining.append(resource)
        self.pending_cleanup = remaining

    async def begin_shutdown(self):
        self.closing = True
        # A candidate finishing its probe now observes closing before commit.
        # A committed swap finishes retirement before the lifecycle drains it.
        async with self.lock:
            pass

    async def close(self):
        # Core lifecycle closes/drains bridge and health before this call.
        await self.begin_shutdown()
        self.pending_cleanup.extend(
            provider.client for provider in self.providers.values()
        )
        self.providers = {}
        await self._cleanup()
        if self.pending_cleanup:
            raise RuntimeError("runtime_owned_resource_cleanup_pending")


def service(plugin) -> RuntimeConfigApplyService:
    existing = getattr(plugin, "_dududa_runtime_config_apply", None)
    if existing is None:
        existing = RuntimeConfigApplyService(plugin)
        plugin._dududa_runtime_config_apply = existing
    return existing


async def runtime_config_status_response(plugin):
    from astrbot.api.web import json_response

    return json_response({"status": "ok", "data": service(plugin).status()})


async def runtime_config_apply_response(plugin):
    from astrbot.api.web import error_response, json_response, request

    try:
        payload = await request.json(default={})
        if (
            not isinstance(payload, dict)
            or set(payload) != {"revision"}
            or type(payload["revision"]) not in (int, str)
        ):
            raise RuntimeApplyError("invalid_apply_request", 400)
        return json_response(
            {"status": "ok", "data": await service(plugin).apply(payload["revision"])}
        )
    except RuntimeApplyError as exc:
        return error_response(exc.code, status_code=exc.status)
    except Exception:  # noqa: BLE001 -- never expose host exception details in HTTP
        return error_response("runtime_apply_failed", status_code=500)
