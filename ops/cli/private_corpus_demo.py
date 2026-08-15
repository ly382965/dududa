"""Generate and locally serve an offline private-corpus inspection page."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
)
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.models.contracts import ModelRole, ModelTier
from dududa.models.policy import (
    TierBudgetRequirement,
    TierPolicyDefinition,
    TierSelectionContext,
)
from dududa.models.tiering import DeterministicModelTierPolicy

WARNINGS = (
    "PRIVATE DEVELOPMENT DATA",
    "SILVER, NOT GOLD",
    "NO SEND",
    "NO MEMORY WRITE",
    "NO TOOL CALL",
    "NO BANDIT",
    "NOT CURRENT DUDUDA BOT TRAFFIC",
    "STUDENT NOT CONNECTED TO PRODUCTION ROUTER",
    "STATIC TIER OFFLINE PREVIEW / 非生产路由",
)
REPORT_CANDIDATES = {
    "inventory": (Path("inventory.json"),),
    "intake": (Path("reports/intake-summary.json"),),
    "windows": (Path("reports/window-summary.json"),),
    "samples": (Path("reports/sample-summary.json"),),
    "teacher_summary": (
        Path("reports/teacher-summary.json"),
        Path("semantic-v2/teacher-summary.json"),
        Path("teacher/summary.json"),
    ),
    "teacher_compile": (Path("reports/teacher-compile-summary.json"),),
    "student_training": (Path("students/training.json"),),
    "student_metrics": (Path("students/metrics.json"),),
    "student_predictions": (Path("students/prediction-summary.json"),),
}
REVIEW_CANDIDATES = (
    Path("teacher/review.jsonl"),
    Path("teacher/label-review.jsonl"),
    Path("reports/teacher-review.json"),
    Path("semantic-v2/teacher-review.json"),
    Path("semantic-v2/review.json"),
    Path("semantic-v2/teacher-review.jsonl"),
    Path("semantic-v2/review.jsonl"),
)
WINDOW_CANDIDATES = (
    Path("semantic-v2/silver.jsonl"),
    Path("windows/teacher-target.jsonl"),
    Path("windows/smoke-50.jsonl"),
    Path("windows/all.jsonl"),
)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ACCOUNT_RE = re.compile(r"(?<!\d)\d{6,12}(?!\d)")
URL_QUERY_RE = re.compile(r"(https?://[^\s?#]+)(?:\?[^\s#]*)?(?:#[^\s]*)?")
TEXT_LIMIT = 4_000
TIER_PREVIEW_NOTICE = "离线预览 / 非生产路由"


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: expected JSON object")
            yield value


def _first_existing(root: Path, candidates: Sequence[Path]) -> Path | None:
    return next((root / item for item in candidates if (root / item).is_file()), None)


def _relative(path: Path | None, root: Path) -> str | None:
    return path.relative_to(root).as_posix() if path is not None else None


def _redact_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    text = PHONE_RE.sub("[PHONE]", text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = URL_QUERY_RE.sub(r"\1", text)
    text = ACCOUNT_RE.sub("[ACCOUNT]", text)
    if len(text) > TEXT_LIMIT:
        return text[:TEXT_LIMIT] + "…"
    return text


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _structured_value(value: object, *, field: str = "") -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _structured_value(item, field=str(key))
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_structured_value(item, field=field) for item in value]
    if isinstance(value, str):
        if (
            field.endswith(("_ref", "_refs", "_id", "_digest", "_revision"))
            or field
            in {
                "action",
                "kind",
                "link_source",
                "reason_codes",
                "speech_acts",
            }
        ):
            return value
        return _redact_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _first_mapping(row: Mapping[str, object], *keys: str) -> Mapping[str, object] | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _public_labels(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    labels: dict[str, object] = {}
    for key in (
        "need_tools",
        "semantic_complexity",
        "answer_profile",
        "task_kind",
        "coarse_topic",
        "teacher_confidence",
        "expected_tool_steps",
        "tool_need_kind",
        "intent",
    ):
        item = value.get(key)
        if key in value and (
            isinstance(item, (bool, int, float, str)) or item is None
        ):
            labels[key] = item
    tool_need = value.get("tool_need")
    if "tool_need_kind" not in labels and isinstance(tool_need, Mapping):
        kind = tool_need.get("kind")
        if isinstance(kind, str):
            labels["tool_need_kind"] = kind
    capabilities = value.get("capability_categories")
    if isinstance(capabilities, list):
        labels["capability_categories"] = [str(item) for item in capabilities]
    return labels or None


def _public_semantic(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    semantic = value.get("semantic")
    body = semantic if isinstance(semantic, Mapping) else value
    output: dict[str, object] = {}
    for key in ("decision", "intents", "entities", "references"):
        if key in body:
            output[key] = _structured_value(body[key], field=key)
    for key in ("topics", "speech_acts", "target_identity_refs"):
        if key in value:
            output[key] = _structured_value(value[key], field=key)
    evidence_refs: set[str] = set()
    for item_key in ("intents", "entities", "references", "topics"):
        items = output.get(item_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, Mapping):
                evidence_refs.update(_string_list(item.get("evidence_refs")))
    output["evidence_refs"] = sorted(evidence_refs)
    return output or None


def _public_window(
    window: Mapping[str, object],
    labels: object = None,
    *,
    semantic: object = None,
    complexity_assessment: object = None,
    validation: object = None,
) -> dict[str, object]:
    messages: list[dict[str, object]] = []
    raw_messages = window.get("messages")
    if isinstance(raw_messages, Sequence) and not isinstance(
        raw_messages, (str, bytes)
    ):
        for message in raw_messages:
            if not isinstance(message, Mapping):
                continue
            messages.append(
                {
                    "message_ref": str(message.get("message_ref") or ""),
                    "sender_ref": str(message.get("sender_ref") or "unknown"),
                    "text": _redact_text(message.get("text")),
                    "reply_to_ref": message.get("reply_to_ref"),
                    "mention_refs": _string_list(message.get("mention_refs")),
                    "attachment_kinds": _string_list(
                        message.get("attachment_kinds")
                    ),
                    "self_authored": bool(message.get("self_authored")),
                }
            )
    buckets = _string_list(window.get("buckets"))
    return {
        "window_id": str(window.get("window_id") or ""),
        "conversation_ref": str(window.get("conversation_ref") or ""),
        "current_message_ref": str(window.get("current_message_ref") or ""),
        "primary_bucket": str(
            window.get("primary_bucket") or (buckets[0] if buckets else "unknown")
        ),
        "buckets": buckets,
        "message_count": len(messages),
        "speaker_count": int(window.get("speaker_count") or 0),
        "messages": messages,
        "silver": _public_labels(labels),
        "semantic": _public_semantic(semantic),
        "complexity_assessment": _structured_value(complexity_assessment),
        "validation": _structured_value(validation),
        "student": None,
        "tier_preview": None,
        "teacher_review": None,
    }


def _tier_preview_definition() -> TierPolicyDefinition:
    return TierPolicyDefinition(
        1,
        "private-corpus-offline-preview",
        ModelRole.DIRECT_CHAT,
        frozenset({ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS}),
        ModelTier.SONNET,
        ModelTier.HAIKU,
        ModelTier.OPUS,
        0.6,
        0.85,
        2,
        frozenset(
            {
                "deep_reasoning",
                "multi_constraint_synthesis",
                "independent_verification",
                "multi_step_tool_plan",
                "cross_artifact_analysis",
            }
        ),
        (
            TierBudgetRequirement(1, ModelTier.HAIKU, 1_000, 256, Decimal("0.1")),
            TierBudgetRequirement(1, ModelTier.SONNET, 2_000, 512, Decimal(1)),
            TierBudgetRequirement(1, ModelTier.OPUS, 4_000, 1_024, Decimal(4)),
        ),
        "private-corpus-offline-preview-v1",
    )


def _offline_static_tier_preview(
    student: object,
    *,
    window_id: str,
) -> dict[str, object] | None:
    if not isinstance(student, Mapping):
        return None
    raw_complexity = student.get("semantic_complexity")
    if not isinstance(raw_complexity, Mapping):
        return None
    label = raw_complexity.get("label")
    confidence = raw_complexity.get("confidence")
    if (
        not isinstance(label, str)
        or label not in {level.value for level in TaskComplexityLevel}
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        return None

    level = TaskComplexityLevel(label)
    reasoning_depth = TaskReasoningDepth.MULTI_STEP
    expected_tool_steps = 1
    verification_required = False
    reason_codes = [f"student_semantic_complexity_{level.value}"]
    if level is TaskComplexityLevel.LOW:
        reasoning_depth = TaskReasoningDepth.SHALLOW
        expected_tool_steps = 0
    elif level is TaskComplexityLevel.HIGH:
        reasoning_depth = TaskReasoningDepth.DEEP
        expected_tool_steps = 2
        verification_required = True
        reason_codes.extend(("deep_reasoning", "multi_constraint_synthesis"))

    assessment = TaskComplexityAssessment(
        schema_version=1,
        assessment_id=f"offline-preview-{window_id}",
        level=level,
        confidence=float(confidence),
        task_kind="offline_student_preview",
        context_pressure=ContextPressure.LOW,
        reasoning_depth=reasoning_depth,
        expected_tool_steps=expected_tool_steps,
        ambiguity=TaskAmbiguity.LOW,
        verification_required=verification_required,
        conflicting_evidence=False,
        reason_codes=tuple(reason_codes),
        evidence_refs=(window_id,),
        assessor_revision=ComponentRevision(
            "private-corpus-student-preview",
            "1.0.0",
            "offline-preview-v1",
            DigestString("artifact:private-corpus-student-preview"),
        ),
    )
    decision = DeterministicModelTierPolicy(
        id_factory=lambda: f"offline-tier-{window_id}"
    ).decide(
        TierSelectionContext(
            1,
            f"offline-selection-{window_id}",
            ModelRole.DIRECT_CHAT,
            assessment,
            1,
            PrivacyLevel.CONVERSATION,
            RuntimeBudget(1, 0, 0, 8_000, 2_000, Decimal(8)),
        ),
        _tier_preview_definition(),
        now=datetime.now(timezone.utc),
    )
    return {
        "kind": "offline_static_tier_preview",
        "source": "student_semantic_complexity",
        "input_complexity": level.value,
        "input_confidence": float(confidence),
        "selected_tier": decision.selected_tier.value,
        "reason_codes": list(decision.reason_codes),
        "production_route": False,
        "notice": TIER_PREVIEW_NOTICE,
    }


def _load_window_samples(
    root: Path, sample_limit: int
) -> tuple[list[dict[str, object]], Path]:
    source = _first_existing(root, WINDOW_CANDIDATES)
    if source is None:
        expected = ", ".join(item.as_posix() for item in WINDOW_CANDIDATES)
        raise FileNotFoundError(f"no window sample source found; expected: {expected}")
    samples: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for row in _read_jsonl(source):
        candidate = row.get("window", row)
        if not isinstance(candidate, Mapping):
            continue
        window_id = str(candidate.get("window_id") or "")
        if not window_id or window_id in seen_ids:
            continue
        labels = _first_mapping(row, "sidecar", "dataset_sidecar", "labels")
        complexity = row.get("complexity_assessment")
        if complexity is None and labels is not None:
            complexity = labels.get("complexity_assessment")
        samples.append(
            _public_window(
                candidate,
                labels,
                semantic=row.get("model_projection_v2"),
                complexity_assessment=complexity,
                validation=row.get("validation"),
            )
        )
        seen_ids.add(window_id)
        if len(samples) >= sample_limit:
            break
    if not samples:
        raise ValueError(f"window sample source is empty: {source}")
    return samples, source


def _load_predictions(
    path: Path | None, window_ids: set[str]
) -> dict[str, Mapping[str, object]]:
    if path is None:
        return {}
    predictions: dict[str, Mapping[str, object]] = {}
    for row in _read_jsonl(path):
        window_id = str(row.get("window_id") or "")
        value = row.get("predictions")
        if window_id in window_ids and isinstance(value, Mapping):
            predictions[window_id] = value
            if len(predictions) == len(window_ids):
                break
    return predictions


def _review_status(row: Mapping[str, object]) -> str:
    for key in ("status", "decision", "review"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    accepted = row.get("accepted")
    if isinstance(accepted, bool):
        return "accepted" if accepted else "rejected"
    return "unknown"


def _public_review(row: Mapping[str, object]) -> dict[str, object]:
    output: dict[str, object] = {"status": _review_status(row)}
    for key in (
        "accepted",
        "decision",
        "reason",
        "issues",
        "stage",
        "reason_code",
        "retryable",
        "http_status",
    ):
        value = row.get(key)
        if key in row and (
            isinstance(value, (bool, int, float, str, list)) or value is None
        ):
            output[key] = _structured_value(value, field=key)
    return output


def _review_rows(value: object) -> Iterator[Mapping[str, object]]:
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, Mapping))
        return
    if not isinstance(value, Mapping):
        return
    for key in ("reviews", "rows", "items"):
        rows = value.get(key)
        if isinstance(rows, list):
            yield from (item for item in rows if isinstance(item, Mapping))
            return


def _load_teacher_review(
    root: Path, window_ids: set[str]
) -> tuple[dict[str, object] | None, dict[str, dict[str, object]], Path | None]:
    path = _first_existing(root, REVIEW_CANDIDATES)
    if path is None:
        return None, {}, None
    if path.suffix == ".jsonl":
        rows: Iterator[Mapping[str, object]] = _read_jsonl(path)
        source_summary: Mapping[str, object] | None = None
    else:
        value = _read_json(path)
        rows = _review_rows(value)
        source_summary = value if isinstance(value, Mapping) else None

    counts: Counter[str] = Counter()
    selected: dict[str, dict[str, object]] = {}
    row_count = 0
    for row in rows:
        row_count += 1
        counts[_review_status(row)] += 1
        window = row.get("window")
        nested_id = window.get("window_id") if isinstance(window, Mapping) else None
        window_id = str(row.get("window_id") or nested_id or "")
        if window_id in window_ids:
            selected[window_id] = _public_review(row)
    summary: dict[str, object] = {
        "row_count": row_count,
        "status_counts": dict(sorted(counts.items())),
    }
    if source_summary is not None:
        for key in ("schema_version", "reviewed", "accepted", "rejected"):
            value = source_summary.get(key)
            if isinstance(value, (bool, int, float, str)):
                summary[key] = value
    return summary, selected, path


def _load_reports(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    reports: dict[str, object] = {}
    sources: dict[str, object] = {}
    for name, candidates in REPORT_CANDIDATES.items():
        path = _first_existing(root, candidates)
        sources[name] = {
            "available": path is not None,
            "path": _relative(path, root),
        }
        if path is not None:
            reports[name] = _read_json(path)
    return reports, sources


def _json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dududa 私有语料离线 Demo</title>
  <style>
    :root { color-scheme: dark; --bg:#08111f; --panel:#101d2f; --line:#26364c;
      --text:#e9f1fb; --muted:#9db0c6; --accent:#78dcca; --warn:#ffc857; }
    * { box-sizing: border-box; }
    body { margin:0; font:14px/1.55 system-ui,sans-serif; color:var(--text);
      background:radial-gradient(circle at top right,#16324a 0,var(--bg) 34%); }
    main { width:min(1440px,calc(100% - 32px)); margin:0 auto; padding:28px 0 60px; }
    h1,h2,h3,p { margin-top:0; }
    h1 { font-size:clamp(25px,4vw,42px); margin-bottom:8px; }
    h2 { margin:30px 0 12px; }
    .muted { color:var(--muted); }
    .warnings,.chips { display:flex; flex-wrap:wrap; gap:8px; }
    .warning,.chip { border:1px solid #6e5924; border-radius:999px; padding:5px 9px;
      background:#2c2515; color:#ffe09a; font-size:11px; font-weight:750; letter-spacing:.04em; }
    .chip { border-color:var(--line); background:#16263a; color:#c8d7e8; font-weight:600; }
    .summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
      gap:12px; margin:20px 0; }
    .metric,.panel,.window { border:1px solid var(--line); border-radius:14px;
      background:rgba(16,29,47,.92); box-shadow:0 12px 35px rgba(0,0,0,.18); }
    .metric { padding:16px; }
    .metric strong { display:block; font-size:25px; color:var(--accent); }
    .panel { padding:16px; }
    .filters { display:grid; grid-template-columns:2fr repeat(4,minmax(135px,1fr)); gap:10px;
      position:sticky; top:0; z-index:2; backdrop-filter:blur(10px); }
    input,select { width:100%; border:1px solid var(--line); border-radius:9px; padding:10px;
      color:var(--text); background:#0a1525; }
    .windows { display:grid; gap:14px; margin-top:14px; }
    .window { padding:16px; }
    .window-head { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }
    .window h3 { margin-bottom:4px; font-size:16px; }
    .compare { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px;
      margin:14px 0; }
    .compare > div { border:1px solid var(--line); border-radius:10px; padding:10px;
      background:#0b1727; }
    .tier-preview { border:2px solid var(--warn); border-radius:10px; padding:12px;
      margin:0 0 14px; background:#2c2515; color:#ffe09a; }
    .tier-preview strong { display:block; letter-spacing:.04em; }
    .messages { display:grid; gap:7px; }
    .message { display:grid; grid-template-columns:minmax(90px,150px) 1fr; gap:10px;
      border-left:3px solid #2d4965; padding:7px 9px; background:#0b1727; border-radius:5px; }
    .speaker { color:var(--accent); overflow-wrap:anywhere; }
    .text { white-space:pre-wrap; overflow-wrap:anywhere; }
    details { border-top:1px solid var(--line); padding:10px 0; }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; color:#bdd0e5; }
    .empty { padding:30px; text-align:center; color:var(--muted); }
    @media (max-width:900px) { .filters { grid-template-columns:1fr 1fr; position:static; }
      .compare { grid-template-columns:1fr; } }
    @media (max-width:560px) { main { width:min(100% - 20px,1440px); }
      .filters { grid-template-columns:1fr; } .message { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<main>
  <header>
    <h1>Dududa 私有语料离线 Demo</h1>
    <p class="muted">检查历史群聊窗口、Teacher Silver 标签、离线 Student 预测与 Static TierPolicy 预览。页面不连接任何 Provider，也不参与生产路由。</p>
    <div class="warnings" id="warnings"></div>
  </header>
  <section class="summary" id="summary"></section>
  <section class="panel">
    <h2>产物状态</h2>
    <div id="sources"></div>
  </section>
  <h2>匿名窗口样本</h2>
  <section class="panel filters">
    <input id="query" type="search" placeholder="搜索匿名文本、窗口或群引用">
    <select id="bucket"><option value="">全部 Bucket</option></select>
    <select id="tools"><option value="">全部工具判断</option></select>
    <select id="complexity"><option value="">全部复杂度</option></select>
    <select id="profile"><option value="">全部回答长度</option></select>
  </section>
  <p class="muted" id="count"></p>
  <section class="windows" id="windows"></section>
  <section class="panel">
    <h2>阶段报告</h2>
    <div id="reports"></div>
  </section>
</main>
<script id="demo-data" type="application/json">__DEMO_DATA__</script>
<script>
(() => {
  const data = JSON.parse(document.getElementById('demo-data').textContent);
  const byId = (id) => document.getElementById(id);
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const addOption = (select, value) => {
    const option = make('option', '', value);
    option.value = value;
    select.append(option);
  };
  data.warnings.forEach((item) => byId('warnings').append(make('span','warning',item)));

  const predicted = data.windows.filter((item) => item.student).length;
  const silver = data.windows.filter((item) => item.silver).length;
  const groups = new Set(data.windows.map((item) => item.conversation_ref)).size;
  [['样本窗口',data.windows.length],['匿名群',groups],['Silver 标签',silver],
   ['Student 预测',predicted]].forEach(([label,value]) => {
    const card = make('div','metric');
    card.append(make('strong','',value),make('span','muted',label));
    byId('summary').append(card);
  });

  Object.entries(data.sources).forEach(([name, source]) => {
    const row = make('div','');
    row.append(make('span','chip',source.available ? '可用' : '待生成'));
    row.append(document.createTextNode(` ${name}: ${source.path || '—'}`));
    byId('sources').append(row);
  });

  const values = (key) => [...new Set(data.windows.map((item) => {
    if (key === 'bucket') return item.primary_bucket;
    if (key === 'tools') return item.silver?.need_tools ?? item.student?.need_tools?.label;
    if (key === 'complexity') return item.silver?.semantic_complexity ?? item.student?.semantic_complexity?.label;
    return item.silver?.answer_profile ?? item.student?.answer_profile?.label;
  }).filter((item) => item !== undefined && item !== null).map(String))].sort();
  ['bucket','tools','complexity','profile'].forEach((key) => {
    values(key).forEach((value) => addOption(byId(key), value));
    byId(key).addEventListener('change', render);
  });
  byId('query').addEventListener('input', render);

  const labelText = (labels) => labels ? Object.entries(labels)
    .map(([key,value]) => `${key}: ${value}`).join('\n') : '暂无';
  const studentText = (student) => student ? Object.entries(student)
    .map(([key,value]) => `${key}: ${value.label} (${Number(value.confidence || 0).toFixed(3)})`)
    .join('\n') : '暂无';
  const tierName = (tier) => ({haiku:'Haiku',sonnet:'Sonnet',opus:'Opus'}[tier] || '暂无');
  const detailBlock = (title, value, open = false) => {
    const block = make('details','');
    block.open = open;
    block.append(make('summary','',title),
      make('pre','',value ? JSON.stringify(value,null,2) : '暂无'));
    return block;
  };

  function windowCard(item) {
    const card = make('article','window');
    const head = make('div','window-head');
    const title = make('div','');
    title.append(make('h3','',item.window_id),make('div','muted',item.conversation_ref));
    const chips = make('div','chips');
    [item.primary_bucket,`${item.message_count} messages`,`${item.speaker_count} speakers`]
      .forEach((value) => chips.append(make('span','chip',value)));
    head.append(title,chips);
    card.append(head);
    const compare = make('div','compare');
    const teacher = make('div','');
    teacher.append(make('strong','','Teacher Silver'),make('pre','',labelText(item.silver)));
    const student = make('div','');
    student.append(make('strong','','Student'),make('pre','',studentText(item.student)));
    compare.append(teacher,student);
    card.append(compare);
    const preview = make('div','tier-preview');
    if (item.tier_preview) {
      preview.append(
        make('strong','','STATIC TIER OFFLINE PREVIEW / 非生产路由'),
        make('div','',`Student semantic complexity: ${item.tier_preview.input_complexity}`),
        make('div','',`→ Static TierPolicy 离线预览 → ${tierName(item.tier_preview.selected_tier)}`),
        make('div','muted',`confidence=${Number(item.tier_preview.input_confidence).toFixed(3)} · ${item.tier_preview.reason_codes.join(', ')}`),
      );
    } else {
      preview.append(
        make('strong','','STATIC TIER OFFLINE PREVIEW / 非生产路由'),
        make('div','',`Student semantic complexity → Static TierPolicy 离线预览 → 暂无`),
      );
    }
    card.append(preview);
    card.append(
      detailBlock('Semantic v2：Decision / Intent / Entity / Reference / Evidence', item.semantic, true),
      detailBlock('Derived Complexity Assessment', item.complexity_assessment),
      detailBlock('Schema / Span / Reference / Round-trip 验证', item.validation),
    );
    const messages = make('div','messages');
    item.messages.forEach((message) => {
      const row = make('div','message');
      row.append(make('span','speaker',message.sender_ref),make('span','text',message.text));
      messages.append(row);
    });
    card.append(messages);
    if (item.teacher_review) {
      const review = make('details','');
      review.append(make('summary','','Teacher review'),
        make('pre','',JSON.stringify(item.teacher_review,null,2)));
      card.append(review);
    }
    return card;
  }

  function render() {
    const query = byId('query').value.trim().toLowerCase();
    const bucket = byId('bucket').value;
    const tools = byId('tools').value;
    const complexity = byId('complexity').value;
    const profile = byId('profile').value;
    const filtered = data.windows.filter((item) => {
      const toolValue = item.silver?.need_tools ?? item.student?.need_tools?.label;
      const complexityValue = item.silver?.semantic_complexity ?? item.student?.semantic_complexity?.label;
      const profileValue = item.silver?.answer_profile ?? item.student?.answer_profile?.label;
      return (!query || JSON.stringify(item).toLowerCase().includes(query))
        && (!bucket || item.primary_bucket === bucket)
        && (!tools || String(toolValue) === tools)
        && (!complexity || String(complexityValue) === complexity)
        && (!profile || String(profileValue) === profile);
    });
    const target = byId('windows');
    target.replaceChildren();
    filtered.forEach((item) => target.append(windowCard(item)));
    if (!filtered.length) target.append(make('div','empty','没有符合筛选条件的窗口。'));
    byId('count').textContent = `显示 ${filtered.length} / ${data.windows.length}`;
  }

  Object.entries(data.reports).forEach(([name, report]) => {
    const block = make('details','');
    block.append(make('summary','',name),make('pre','',JSON.stringify(report,null,2)));
    byId('reports').append(block);
  });
  render();
})();
</script>
</body>
</html>
"""


def generate_demo(
    output_root: Path | str, sample_limit: int = 300
) -> dict[str, object]:
    """Generate a self-contained HTML demo without network dependencies."""

    if sample_limit < 1:
        raise ValueError("sample_limit must be positive")
    root = Path(output_root).expanduser().resolve()
    windows, window_source = _load_window_samples(root, sample_limit)
    window_ids = {str(item["window_id"]) for item in windows}

    predictions_path = root / "students/predictions.jsonl"
    if not predictions_path.is_file():
        predictions_path = None
    predictions = _load_predictions(predictions_path, window_ids)
    review_summary, reviews, review_path = _load_teacher_review(root, window_ids)
    for window in windows:
        window_id = str(window["window_id"])
        window["student"] = predictions.get(window_id)
        window["tier_preview"] = _offline_static_tier_preview(
            window["student"],
            window_id=window_id,
        )
        window["teacher_review"] = reviews.get(window_id)

    reports, sources = _load_reports(root)
    if review_summary is not None:
        reports["teacher_review"] = review_summary
    sources.update(
        {
            "window_samples": {
                "available": True,
                "path": _relative(window_source, root),
            },
            "teacher_review": {
                "available": review_path is not None,
                "path": _relative(review_path, root),
            },
            "student_predictions": {
                "available": predictions_path is not None,
                "path": _relative(predictions_path, root),
            },
        }
    )
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": list(WARNINGS),
        "sources": sources,
        "reports": reports,
        "windows": windows,
    }
    demo_path = root / "demo/index.html"
    demo_path.parent.mkdir(parents=True, exist_ok=True)
    demo_path.write_text(
        HTML_TEMPLATE.replace("__DEMO_DATA__", _json_for_script(payload)),
        encoding="utf-8",
    )
    return {
        "demo_path": str(demo_path),
        "sample_count": len(windows),
        "silver_sample_count": sum(bool(item.get("silver")) for item in windows),
        "prediction_sample_count": len(predictions),
        "review_sample_count": len(reviews),
        "window_source": _relative(window_source, root),
        "offline": True,
    }


def serve_demo(
    output_root: Path | str, host: str = "127.0.0.1", port: int = 8765
) -> None:
    """Serve the generated demo on a loopback interface only."""

    normalized_host = host.strip("[]")
    if host != "localhost":
        try:
            loopback = ipaddress.ip_address(normalized_host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("serve_demo only accepts a loopback host")
    root = Path(output_root).expanduser().resolve()
    demo_directory = root / "demo"
    if not (demo_directory / "index.html").is_file():
        generate_demo(root)
    handler = partial(SimpleHTTPRequestHandler, directory=str(demo_directory))
    server_type = _IPv6ThreadingHTTPServer if ":" in normalized_host else ThreadingHTTPServer
    with server_type((normalized_host, port), handler) as server:
        print(f"Dududa private demo: http://{host}:{server.server_port}/")
        server.serve_forever()
