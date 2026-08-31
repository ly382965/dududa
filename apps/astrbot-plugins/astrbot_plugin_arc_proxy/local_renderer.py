from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import JsonValue

_ARTIFACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MAX_SCORES = 50


class LocalB50RendererError(RuntimeError):
    """The local renderer could not produce a B50 artifact."""


@runtime_checkable
class B50RendererPort(Protocol):
    async def render(
        self, request: Mapping[str, JsonValue]
    ) -> Mapping[str, JsonValue]: ...

    async def close(self) -> None: ...


RenderEngine = Callable[
    [Path, Path, Path, Path, Path, Path],
    Mapping[str, JsonValue],
]


class LocalB50Renderer:
    """Render structured B50 facts into a local PNG without any messaging API."""

    def __init__(
        self,
        *,
        renderer_script: Path,
        assets_root: Path,
        artifact_root: Path,
        background_path: Path | None = None,
        font_directory: Path | None = None,
        asset_dataset_id: str = "arcaea-assets-local",
        engine: RenderEngine | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._renderer_script = Path(renderer_script)
        self._assets_root = Path(assets_root)
        self._artifact_root = Path(artifact_root)
        renderer_root = self._renderer_script.parent
        self._background_path = Path(
            background_path or renderer_root / "background.png"
        )
        self._font_directory = Path(font_directory or renderer_root / "fonts")
        self._asset_dataset_id = str(asset_dataset_id).strip()
        self._engine = engine or _repository_render_engine
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._closed = False

    @classmethod
    def from_repository(
        cls,
        *,
        assets_root: Path,
        artifact_root: Path,
        asset_dataset_id: str = "arcaea-assets-local",
    ) -> LocalB50Renderer:
        renderer_root = Path(__file__).resolve().parents[2] / "b50-renderer"
        return cls(
            renderer_script=renderer_root / "b50_renderer.py",
            assets_root=assets_root,
            artifact_root=artifact_root,
            asset_dataset_id=asset_dataset_id,
        )

    async def render(self, request: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        if self._closed:
            raise LocalB50RendererError("B50 renderer is closed")
        payload = _structured_payload(request)
        artifact_id = str(self._id_factory())
        if _ARTIFACT_ID.fullmatch(artifact_id) is None:
            raise LocalB50RendererError("invalid B50 artifact id")
        artifact_path = self._artifact_root / f"b50-{artifact_id}.png"
        self._artifact_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="dududa-b50-") as raw:
            input_path = Path(raw) / "b50.json"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                statistics = await asyncio.to_thread(
                    self._engine,
                    self._renderer_script,
                    input_path,
                    self._assets_root,
                    artifact_path,
                    self._background_path,
                    self._font_directory,
                )
            except Exception as exc:
                artifact_path.unlink(missing_ok=True)
                raise LocalB50RendererError("local B50 render failed") from exc

        if not artifact_path.is_file():
            raise LocalB50RendererError("local B50 renderer produced no artifact")
        generated_at = _aware_utc(self._clock())
        return {
            "schema_version": 1,
            "artifact": {
                "path": str(artifact_path),
                "media_type": "image/png",
                "byte_size": artifact_path.stat().st_size,
            },
            "statistics": _plain_json(statistics),
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "provenance": {
                "renderer": "dududa-b50-renderer",
                "renderer_revision": "repository-v1",
                "asset_dataset_id": self._asset_dataset_id,
                "input_record_count": len(payload["scores"]),
                "execution": "local_in_process",
            },
        }

    async def close(self) -> None:
        self._closed = True


def _repository_render_engine(
    renderer_script: Path,
    input_path: Path,
    assets_root: Path,
    output_path: Path,
    background_path: Path,
    font_directory: Path,
) -> Mapping[str, JsonValue]:
    module = _load_renderer_module(renderer_script)
    catalog = module.SongCatalog(assets_root)
    records, player = module.load_input(input_path, catalog)
    top10, top50, maximum, jacket_count = module.render(
        records,
        player,
        catalog,
        background_path,
        font_directory,
        output_path,
    )
    return {
        "record_count": len(records),
        "top10_average": top10,
        "top50_average": top50,
        "maximum_potential": maximum,
        "resolved_jacket_count": jacket_count,
    }


def _load_renderer_module(path: Path) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError("B50 renderer script is unavailable")
    module_name = f"dududa_b50_renderer_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load B50 renderer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _structured_payload(request: Mapping[str, JsonValue]) -> dict[str, object]:
    if not isinstance(request, Mapping):
        raise TypeError("B50 request must be a mapping")
    player = request.get("player")
    scores = request.get("scores")
    if not isinstance(player, Mapping):
        raise TypeError("B50 player must be an object")
    if not isinstance(scores, (list, tuple)) or not 1 <= len(scores) <= _MAX_SCORES:
        raise ValueError("B50 scores must contain 1 to 50 records")
    if any(not isinstance(item, Mapping) for item in scores):
        raise ValueError("B50 score records must be objects")
    return {
        "player": _plain_json(player),
        "scores": [_plain_json(item) for item in scores],
    }


def _plain_json(value):
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("B50 renderer clock must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "B50RendererPort",
    "LocalB50Renderer",
    "LocalB50RendererError",
]
