from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
import unittest

from dududa.contracts.binding import (
    PortBindingRequirement,
    PortDescriptor,
    PortOperationDescriptor,
    PortOperationRequirement,
    bind_port,
)
from dududa.contracts.versioning import VersionedReader
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    SchemaRef,
)
from dududa.errors import DududaError, ErrorCategory


def schema(schema_id: str, version: int, digest: str) -> SchemaRef:
    return SchemaRef(schema_id, version, DigestString(digest))


@runtime_checkable
class RunnablePort(Protocol):
    def run(self) -> None: ...


class RunnableImplementation:
    def run(self) -> None:
        return None


class PortBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.input_schema = schema("runtime.request", 1, "request-v1")
        self.output_v1 = schema("runtime.result", 1, "result-v1")
        self.output_v2 = schema("runtime.result", 2, "result-v2")
        self.requirement = PortBindingRequirement(
            port_id="agent-runtime",
            protocol_major=1,
            operations=(
                PortOperationRequirement(
                    "run",
                    self.input_schema,
                    (self.output_v1, self.output_v2),
                ),
            ),
            required_capability_flags=frozenset({"delivery_ack"}),
        )
        self.descriptor = PortDescriptor(
            port_id="agent-runtime",
            protocol_version="1.2.0",
            operations=(
                PortOperationDescriptor(
                    "run",
                    (self.input_schema,),
                    (self.output_v1, self.output_v2),
                ),
            ),
            supported_capability_flags=frozenset({"delivery_ack", "reconcile"}),
            component_revision=ComponentRevision(
                "fake.runtime", "1.0.0", "cfg-1", DigestString("artifact")
            ),
        )

    def test_negotiates_every_operation_and_capability(self) -> None:
        implementation = RunnableImplementation()
        binding, receipt = bind_port(
            self.requirement,
            self.descriptor,
            implementation,
            implementation_protocol=RunnablePort,
            negotiated_at=datetime.now(timezone.utc),
        )
        self.assertIs(binding.implementation, implementation)
        self.assertEqual(
            receipt.operation_schema_digests["run"],
            (DigestString("request-v1"), DigestString("result-v2")),
        )
        self.assertEqual(receipt.enabled_capability_flags, frozenset({"delivery_ack"}))
        with self.assertRaises(TypeError):
            receipt.operation_schema_digests["other"] = (  # type: ignore[index]
                DigestString("a"),
                DigestString("b"),
            )

    def test_rejects_major_schema_operation_and_capability_mismatch(self) -> None:
        incompatible = (
            PortDescriptor(
                self.descriptor.port_id,
                "2.0.0",
                self.descriptor.operations,
                self.descriptor.supported_capability_flags,
                self.descriptor.component_revision,
            ),
            PortDescriptor(
                self.descriptor.port_id,
                "1.0.0",
                (
                    PortOperationDescriptor(
                        "run",
                        (schema("runtime.request", 1, "tampered"),),
                        (self.output_v2,),
                    ),
                ),
                self.descriptor.supported_capability_flags,
                self.descriptor.component_revision,
            ),
            PortDescriptor(
                self.descriptor.port_id,
                "1.0.0",
                (
                    PortOperationDescriptor(
                        "health", (self.input_schema,), (self.output_v2,)
                    ),
                ),
                self.descriptor.supported_capability_flags,
                self.descriptor.component_revision,
            ),
            PortDescriptor(
                self.descriptor.port_id,
                "1.0.0",
                self.descriptor.operations,
                frozenset(),
                self.descriptor.component_revision,
            ),
        )
        for descriptor in incompatible:
            with self.subTest(descriptor=descriptor):
                with self.assertRaises(DududaError) as raised:
                    bind_port(
                        self.requirement,
                        descriptor,
                        RunnableImplementation(),
                        implementation_protocol=RunnablePort,
                        negotiated_at=datetime.now(timezone.utc),
                    )
                self.assertEqual(raised.exception.info.category, ErrorCategory.CONFLICT)

    def test_reader_accepts_only_n_and_n_minus_one(self) -> None:
        def upcast(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
            return {
                "schema_version": 2,
                "value": payload["legacy_value"],
            }

        reader = VersionedReader(
            schema_id="fixture",
            current_version=2,
            decoder=lambda payload: str(payload["value"]),
            upcasters={1: upcast},
        )
        self.assertEqual(
            reader.read({"schema_version": 2, "value": "current"}), "current"
        )
        self.assertEqual(
            reader.read({"schema_version": 1, "legacy_value": "previous"}),
            "previous",
        )
        for version in (0, 3):
            with self.subTest(version=version):
                with self.assertRaises(DududaError):
                    reader.read({"schema_version": version, "value": "invalid"})

    def test_binding_inputs_are_defensively_frozen(self) -> None:
        operations = [self.descriptor.operations[0]]
        flags = {"delivery_ack"}
        descriptor = PortDescriptor(
            self.descriptor.port_id,
            self.descriptor.protocol_version,
            operations,  # type: ignore[arg-type]
            flags,  # type: ignore[arg-type]
            self.descriptor.component_revision,
        )
        operations.clear()
        flags.clear()
        self.assertEqual(len(descriptor.operations), 1)
        self.assertEqual(
            descriptor.supported_capability_flags, frozenset({"delivery_ack"})
        )

    def test_rejects_nonconforming_implementation(self) -> None:
        with self.assertRaises(DududaError):
            bind_port(
                self.requirement,
                self.descriptor,
                object(),
                implementation_protocol=RunnablePort,
                negotiated_at=datetime.now(timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
