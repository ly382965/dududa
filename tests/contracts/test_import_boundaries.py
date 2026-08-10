from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packages" / "dududa-agent" / "src" / "dududa"
PUBLIC_PACKAGES = (
    "dududa",
    "dududa.adapters",
    "dududa.capabilities",
    "dududa.compatibility",
    "dududa.config",
    "dududa.contracts",
    "dududa.domain",
    "dududa.evaluation",
    "dududa.memory",
    "dududa.mcp",
    "dududa.models",
    "dududa.perception",
    "dududa.ports",
    "dududa.rollout",
    "dududa.responses",
    "dududa.runtime",
    "dududa.security",
    "dududa.testing",
)
ORDER_SENSITIVE_MODULES = (
    "dududa.capabilities.authorization",
    "dududa.capabilities.config",
    "dududa.capabilities.contracts",
    "dududa.capabilities.executor",
    "dududa.capabilities.health",
    "dududa.capabilities.ledger",
    "dududa.capabilities.mapping_policy",
    "dududa.capabilities.mcp_provider",
    "dududa.capabilities.planning",
    "dududa.capabilities.registry",
    "dududa.capabilities.retrieval",
    "dududa.capabilities.runtime",
    "dududa.capabilities.validation",
    "dududa.domain.attachments",
    "dududa.domain.delivery",
    "dududa.domain.task",
    "dududa.models.contracts",
    "dududa.models.errors",
    "dududa.models.policy",
    "dududa.perception.complexity",
    "dududa.perception.contracts",
    "dududa.perception.social",
    "dududa.memory.lexical",
    "dududa.memory.retrieval",
    "dududa.mcp.client",
    "dududa.mcp.contracts",
    "dududa.mcp.registry",
    "dududa.mcp.subprocess_v2",
    "dududa.ports.context",
    "dududa.ports.mcp",
    "dududa.ports.memory",
    "dududa.ports.models",
    "dududa.ports.perception",
    "dududa.ports.runtime",
    "dududa.ports.responses",
    "dududa.rollout.admission",
    "dududa.rollout.canary",
    "dududa.rollout.contracts",
    "dududa.rollout.ledger",
    "dududa.rollout.metrics",
    "dududa.rollout.ports",
    "dududa.rollout.rollback",
    "dududa.rollout.shadow",
    "dududa.responses.contracts",
    "dududa.responses.counting",
    "dududa.responses.policy",
    "dududa.responses.validation",
    "dududa.runtime.composition",
    "dududa.runtime.context",
    "dududa.runtime.contracts",
    "dududa.runtime.authorization",
    "dududa.runtime.budget",
    "dududa.runtime.delivery",
    "dududa.runtime.direct_chat",
    "dududa.runtime.offline",
    "dududa.runtime.orchestrator",
    "dududa.runtime.perception",
    "dududa.runtime.selection",
    "dududa.runtime.shadow",
    "dududa.runtime.state",
    "dududa.runtime.store",
    "dududa.security.models",
)

FORBIDDEN_INTERNAL_IMPORTS = {
    "dududa.perception": ("dududa.models", "dududa.runtime"),
    "dududa.models": ("dududa.perception", "dududa.runtime"),
    "dududa.responses": ("dududa.models", "dududa.runtime"),
}


class ImportBoundaryTests(unittest.TestCase):
    def test_s15_response_exports_are_visible_and_framework_neutral(self) -> None:
        import importlib

        ports = importlib.import_module("dududa.ports")
        responses = importlib.import_module("dududa.responses")
        expected_owners = {
            "AnswerProfile": "dududa.responses.contracts",
            "DeterministicResponseProfileValidator": "dududa.responses.validation",
            "ResponsePlan": "dududa.responses.contracts",
            "ResponseProfileValidationResult": "dududa.domain.content",
            "DeterministicResponseProfilePolicy": "dududa.responses.policy",
            "UnicodeVisibleTokenCounter": "dududa.responses.counting",
        }
        self.assertLessEqual(set(expected_owners), set(responses.__all__))
        self.assertLessEqual(
            {
                "ResponseProfilePolicy",
                "ResponseProfileValidator",
                "VisibleTokenCounter",
            },
            set(ports.__all__),
        )
        self.assertEqual(len(responses.__all__), len(set(responses.__all__)))
        for name, module_name in expected_owners.items():
            with self.subTest(name=name):
                owner = importlib.import_module(module_name)
                self.assertIs(getattr(responses, name), getattr(owner, name))

    def test_s14_memory_exports_are_visible_and_owned_by_their_modules(self) -> None:
        import importlib

        memory = importlib.import_module("dududa.memory")
        ports = importlib.import_module("dududa.ports")
        expected_memory_owners = {
            "CjkBm25MemoryRanker": "dududa.memory.lexical",
            "DeterministicMemoryRetrievalPolicy": "dududa.memory.retrieval",
            "DeterministicScopedMemoryRetriever": "dududa.memory.retrieval",
            "MemoryDeleteCommand": "dududa.memory.models",
            "MemoryRetrievalResult": "dududa.memory.models",
            "MemoryTombstone": "dududa.memory.models",
        }
        expected_ports = {
            "MemoryAdministration",
            "MemoryRanker",
            "MemoryRepository",
            "MemoryRetrievalPolicy",
            "ScopedMemoryRetriever",
        }
        self.assertLessEqual(set(expected_memory_owners), set(memory.__all__))
        self.assertLessEqual(expected_ports, set(ports.__all__))
        self.assertEqual(len(memory.__all__), len(set(memory.__all__)))
        for name, module_name in expected_memory_owners.items():
            with self.subTest(name=name):
                owner = importlib.import_module(module_name)
                self.assertIs(getattr(memory, name), getattr(owner, name))

    def test_s11_rollout_exports_are_visible_and_framework_neutral(self) -> None:
        import importlib

        rollout = importlib.import_module("dududa.rollout")
        expected_owners = {
            "CanaryCoordinator": "dududa.rollout.canary",
            "RolloutControlConfig": "dududa.rollout.contracts",
            "SQLiteRolloutLedger": "dududa.rollout.ledger",
            "InMemoryRolloutMetrics": "dududa.rollout.metrics",
            "RolloutOwnershipLedger": "dududa.rollout.ports",
            "RollbackManifest": "dududa.rollout.rollback",
            "BoundedShadowSupervisor": "dududa.rollout.shadow",
        }
        self.assertLessEqual(set(expected_owners), set(rollout.__all__))
        self.assertEqual(len(rollout.__all__), len(set(rollout.__all__)))
        for name, module_name in expected_owners.items():
            with self.subTest(name=name):
                owner = importlib.import_module(module_name)
                self.assertIs(getattr(rollout, name), getattr(owner, name))

    def test_runtime_exports_are_visible_and_owned_by_their_modules(self) -> None:
        import importlib

        ports = importlib.import_module("dududa.ports")
        runtime = importlib.import_module("dududa.runtime")
        expected_ports = {
            "AgentRuntime",
            "OfflineFinalResponseValidator",
            "OfflinePersonaRenderer",
            "OfflineRenderValidator",
            "OfflineResponseComposer",
            "RuntimePerceptionEngine",
            "RuntimeStateStore",
            "ShadowReceiptSink",
        }
        expected_runtime_owners = {
            "CurrentMessageContextBuilder": "dududa.runtime.context",
            "DeliveryRequestBuilder": "dududa.runtime.delivery",
            "DirectChatModelCall": "dududa.runtime.direct_chat",
            "InMemoryRuntimeStateStore": "dududa.runtime.store",
            "OfflineDeliveryDriver": "dududa.runtime.offline",
            "OfflineRuntimeOrchestrator": "dududa.runtime.orchestrator",
            "RuntimeModelBudgetPlan": "dududa.runtime.budget",
            "RuntimeToolBudgetPlan": "dududa.runtime.budget",
            "ShadowRunner": "dududa.runtime.shadow",
        }
        expected_runtime = {
            "CompletionReceipt",
            "ConnectorResult",
            "CurrentMessageContext",
            "CurrentMessageContextBuilder",
            "CurrentMessageContextBuilderConfig",
            "DeliveryReconciliationAction",
            "DeliveryReconciliationReceipt",
            "DeliveryRequestBuilder",
            "DeliveryRequestBuilderConfig",
            "DeliveryRequestPlan",
            "DeterministicPersonaRenderer",
            "DeterministicPersonaRendererConfig",
            "DeterministicRenderValidator",
            "DirectChatContent",
            "DirectChatExecutionReceipt",
            "DirectChatFailureReceipt",
            "DirectChatModelCall",
            "DirectChatModelCallConfig",
            "FinalResponseSafetyValidator",
            "HybridPerceptionEngine",
            "InMemoryRuntimeStateStore",
            "InMemoryRuntimeStateStoreConfig",
            "MinimalResponseComposer",
            "MinimalResponseComposerConfig",
            "OfflineDeliveryDriver",
            "OfflineDeliveryRunResult",
            "OfflinePreprocessReceipt",
            "OfflineRuntimeOrchestrator",
            "OfflineRuntimeOrchestratorConfig",
            "OfflineRuntimePolicySnapshot",
            "Outcome",
            "PerceptionExecutionReceipt",
            "RouterBackedModelPerception",
            "RouterBackedModelPerceptionConfig",
            "RuntimeAdmissionAction",
            "RuntimeCheckpoint",
            "RuntimeCommitDisposition",
            "RuntimeCommitRequest",
            "RuntimeCommitResult",
            "RuntimeDedupRecord",
            "RuntimeDirectChatFailure",
            "RuntimeIdentityBinding",
            "RuntimeInvocationOptions",
            "RuntimeModelBudgetPlan",
            "RuntimeModelPerceptionFailure",
            "RuntimePhase",
            "RuntimeResult",
            "RuntimeSelectionSummary",
            "RuntimeStartRequest",
            "RuntimeState",
            "RuntimeToolBudgetPlan",
            "ShadowRunReceipt",
            "ShadowRunner",
            "TraceEvent",
            "TraceSummary",
            "acknowledge_delivery_state",
            "current_message_context_digest",
            "delivery_acknowledgement_states",
            "direct_chat_content_digest",
            "project_s10_decision_signals",
            "project_tier_selection_context",
            "reconcile_completed_delivery",
            "runtime_start_digest",
            "select_model_tier",
            "serialize_perception_context",
            "transition",
            "validate_runtime_state",
            "validate_selection_configuration",
        }
        self.assertLessEqual(expected_ports, set(ports.__all__))
        self.assertEqual(expected_runtime, set(runtime.__all__))
        self.assertEqual(len(runtime.__all__), len(set(runtime.__all__)))
        self.assertLessEqual(set(ports.__all__), set(dir(ports)))
        self.assertLessEqual(set(runtime.__all__), set(dir(runtime)))
        for name, module_name in expected_runtime_owners.items():
            with self.subTest(name=name):
                owner = importlib.import_module(module_name)
                self.assertIs(getattr(runtime, name), getattr(owner, name))

    def test_s10_default_composition_implements_offline_ports(self) -> None:
        from dududa.ports.runtime import (
            OfflineFinalResponseValidator,
            OfflinePersonaRenderer,
            OfflineRenderValidator,
            OfflineResponseComposer,
        )
        from dududa.runtime.composition import (
            DeterministicPersonaRenderer,
            DeterministicRenderValidator,
            FinalResponseSafetyValidator,
            MinimalResponseComposer,
        )

        for implementation, protocol in (
            (MinimalResponseComposer, OfflineResponseComposer),
            (DeterministicPersonaRenderer, OfflinePersonaRenderer),
            (DeterministicRenderValidator, OfflineRenderValidator),
            (FinalResponseSafetyValidator, OfflineFinalResponseValidator),
        ):
            with self.subTest(implementation=implementation.__name__):
                self.assertTrue(issubclass(implementation, protocol))

    def test_core_has_only_standard_library_and_internal_imports(self) -> None:
        violations: list[str] = []
        for path in SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif (
                    isinstance(node, ast.ImportFrom) and node.module and node.level == 0
                ):
                    names.append(node.module)
                for name in names:
                    root = name.split(".", 1)[0]
                    if root != "dududa" and root not in sys.stdlib_module_names:
                        violations.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(violations, [])

    def test_selection_packages_preserve_one_way_internal_dependencies(self) -> None:
        violations: list[str] = []
        for owner, forbidden in FORBIDDEN_INTERNAL_IMPORTS.items():
            package = SOURCE / owner.rsplit(".", 1)[-1]
            for path in package.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = tuple(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = (node.module,) if node.level == 0 else ()
                    else:
                        names = ()
                    for name in names:
                        if any(
                            name == prefix or name.startswith(f"{prefix}.")
                            for prefix in forbidden
                        ):
                            violations.append(
                                f"{path.relative_to(ROOT)}: {owner} imports {name}"
                            )
        self.assertEqual(violations, [])

    def test_shadow_runtime_has_no_side_effect_capability_imports(self) -> None:
        path = SOURCE / "runtime" / "shadow.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level:
                    imported.add(f"dududa.runtime.{node.module}")
                else:
                    imported.add(node.module)
        forbidden = (
            "dududa.ports.output",
            "dududa.ports.memory",
            "dududa.memory",
            "dududa.runtime.offline",
            "dududa.runtime.delivery",
            "dududa.capabilities",
            "astrbot",
            "plugins",
            "mcp",
        )
        violations = sorted(
            name
            for name in imported
            if any(
                name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden
            )
        )
        self.assertEqual(violations, [])

    def test_public_packages_are_valid_first_imports(self) -> None:
        for module in PUBLIC_PACKAGES + ORDER_SENSITIVE_MODULES:
            with self.subTest(module=module):
                self._assert_clean_import(
                    (module,),
                    resolve_exports=module in ORDER_SENSITIVE_MODULES,
                )

    def test_public_exports_survive_forward_and_reverse_import_order(self) -> None:
        for modules in (PUBLIC_PACKAGES, tuple(reversed(PUBLIC_PACKAGES))):
            with self.subTest(first=modules[0]):
                self._assert_clean_import(modules, resolve_exports=True)

    def _assert_clean_import(
        self,
        modules: tuple[str, ...],
        *,
        resolve_exports: bool = False,
    ) -> None:
        source = str(ROOT / "packages" / "dududa-agent" / "src")
        statements = [f"import {module}" for module in modules]
        if resolve_exports:
            statements.extend(
                (
                    "import importlib",
                    (
                        "packages=[importlib.import_module(name) "
                        f"for name in {PUBLIC_PACKAGES!r}]"
                    ),
                    (
                        "[[getattr(package, name) "
                        "for name in getattr(package, '__all__', ())] "
                        "for package in packages]"
                    ),
                )
            )
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (source, environment.get("PYTHONPATH", "")) if item
        )
        completed = subprocess.run(
            [sys.executable, "-c", ";".join(statements)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
