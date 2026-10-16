from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Generic, Mapping, TypeVar

from dududa.domain.primitives import JsonValue
from dududa.errors import validation_error


T = TypeVar("T")
Decoder = Callable[[Mapping[str, JsonValue]], T]
Upcaster = Callable[[Mapping[str, JsonValue]], Mapping[str, JsonValue]]


@dataclass(frozen=True, slots=True)
class VersionedReader(Generic[T]):
    """Read the current schema and exactly N-1 through an explicit upcaster."""

    schema_id: str
    current_version: int
    decoder: Decoder[T]
    upcasters: Mapping[int, Upcaster]

    def __post_init__(self) -> None:
        if not self.schema_id.strip() or self.current_version < 1:
            raise validation_error("invalid_versioned_reader")
        allowed = {self.current_version - 1} if self.current_version > 1 else set()
        if set(self.upcasters) - allowed:
            raise validation_error("unsupported_upcaster_history")
        if self.current_version > 1 and self.current_version - 1 not in self.upcasters:
            raise validation_error("missing_previous_version_upcaster")
        object.__setattr__(self, "upcasters", MappingProxyType(dict(self.upcasters)))

    def read(self, payload: Mapping[str, JsonValue]) -> T:
        version = payload.get("schema_version")
        if type(version) is not int:
            raise validation_error("missing_schema_version", self.schema_id)
        if version == self.current_version:
            normalized = payload
        elif version == self.current_version - 1 and version in self.upcasters:
            normalized = self.upcasters[version](payload)
            if normalized.get("schema_version") != self.current_version:
                raise validation_error("invalid_upcaster_result", self.schema_id)
        else:
            raise validation_error(
                "unsupported_schema_version", self.schema_id, str(version)
            )
        return self.decoder(normalized)
