"""Train and run small offline student models over compiled Silver labels."""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.pipeline import Pipeline

TASKS = ("need_tools", "semantic_complexity", "answer_profile")
SILVER_CANDIDATES = (
    Path("semantic-v2/silver.jsonl"),
    Path("semantic-v2/compiled-silver.jsonl"),
    Path("semantic-v2/compiled.jsonl"),
)
BATCH_SIZE = 256


@dataclass(frozen=True, slots=True)
class _Example:
    window_id: str
    conversation_ref: str
    text: str
    labels: dict[str, bool | str]


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: expected JSON object")
            yield value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _silver_path(output_root: Path) -> Path:
    for relative_path in SILVER_CANDIDATES:
        candidate = output_root / relative_path
        if candidate.is_file():
            return candidate
    expected = ", ".join(str(output_root / item) for item in SILVER_CANDIDATES)
    raise FileNotFoundError(f"compiled Silver JSONL not found; expected one of: {expected}")


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _window_text(window: Mapping[str, object]) -> str:
    messages = window.get("messages")
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        raise TypeError("window.messages must be an array")
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise TypeError("window.messages entries must be objects")
        sender_ref = message.get("sender_ref")
        text = message.get("text")
        speaker = sender_ref if isinstance(sender_ref, str) and sender_ref else "unknown"
        content = text if isinstance(text, str) else ""
        lines.append(f"<speaker:{speaker}> {content}")
    return "\n".join(lines) or "<empty-window>"


def _extract_window(row: Mapping[str, object]) -> Mapping[str, object]:
    candidate = row.get("window", row)
    if not isinstance(candidate, Mapping):
        raise TypeError("window must be an object")
    return candidate


def _load_examples(path: Path) -> list[_Example]:
    examples: list[_Example] = []
    seen_window_ids: set[str] = set()
    for row in _read_jsonl(path):
        window = _extract_window(row)
        sidecar = next(
            (
                row[key]
                for key in ("sidecar", "dataset_sidecar", "labels")
                if isinstance(row.get(key), Mapping)
            ),
            None,
        )
        if not isinstance(sidecar, Mapping):
            raise TypeError(
                "compiled Silver row must contain sidecar, dataset_sidecar or labels"
            )

        window_id = _required_string(window.get("window_id"), "window.window_id")
        if window_id in seen_window_ids:
            raise ValueError(f"duplicate window_id: {window_id}")
        seen_window_ids.add(window_id)
        conversation_ref = _required_string(
            window.get("conversation_ref"), "window.conversation_ref"
        )

        need_tools = sidecar.get("need_tools")
        semantic_complexity = sidecar.get("semantic_complexity")
        answer_profile = sidecar.get("answer_profile")
        if not isinstance(need_tools, bool):
            raise TypeError(f"{window_id}: need_tools must be boolean")
        if not isinstance(semantic_complexity, str) or not semantic_complexity:
            raise ValueError(f"{window_id}: semantic_complexity must be a string")
        if not isinstance(answer_profile, str) or not answer_profile:
            raise ValueError(f"{window_id}: answer_profile must be a string")

        examples.append(
            _Example(
                window_id=window_id,
                conversation_ref=conversation_ref,
                text=_window_text(window),
                labels={
                    "need_tools": need_tools,
                    "semantic_complexity": semantic_complexity,
                    "answer_profile": answer_profile,
                },
            )
        )
    if not examples:
        raise ValueError(f"compiled Silver dataset is empty: {path}")
    return examples


def _group_split(
    examples: Sequence[_Example], seed: int
) -> tuple[list[_Example], list[_Example], list[str], list[str]]:
    groups = sorted({example.conversation_ref for example in examples})
    if len(groups) < 2:
        raise ValueError("at least two conversation_ref groups are required")
    random.Random(seed).shuffle(groups)
    test_group_count = max(1, round(len(groups) * 0.2))
    test_group_count = min(test_group_count, len(groups) - 1)
    test_groups = sorted(groups[:test_group_count])
    train_groups = sorted(groups[test_group_count:])
    test_group_set = set(test_groups)
    train = [
        example
        for example in examples
        if example.conversation_ref not in test_group_set
    ]
    test = [
        example
        for example in examples
        if example.conversation_ref in test_group_set
    ]
    return train, test, train_groups, test_groups


def _new_model(seed: int) -> Pipeline:
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    min_df=2,
                    max_features=50_000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1_000,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ]
    )


def _model_path(output_root: Path, task: str) -> Path:
    return output_root / "students/models" / f"{task}.joblib"


def _json_label(value: object) -> bool | int | float | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _label_key(value: object) -> str:
    label = _json_label(value)
    if isinstance(label, bool):
        return "true" if label else "false"
    return str(label)


def _unique_labels(*values: Sequence[object]) -> list[object]:
    labels: dict[str, object] = {}
    for sequence in values:
        for value in sequence:
            labels.setdefault(_label_key(value), value)
    return [labels[key] for key in sorted(labels)]


def _metric_bundle(
    expected: Sequence[object],
    predicted: Sequence[object],
    labels: Sequence[object],
) -> dict[str, object]:
    return {
        "accuracy": float(accuracy_score(expected, predicted)),
        "macro_f1": float(
            f1_score(
                expected,
                predicted,
                labels=labels,
                average="macro",
                zero_division=0,
            )
        ),
        "weighted_f1": float(
            f1_score(
                expected,
                predicted,
                labels=labels,
                average="weighted",
                zero_division=0,
            )
        ),
    }


def _static_rule_label(
    task: str,
    text: str,
    available: Mapping[str, object],
    majority: object,
) -> object:
    length = len(text)
    if task == "need_tools":
        candidate: object = bool(
            re.search(
                r"最新|实时|搜索|查一下|查询|天气|新闻|论文|arxiv|评课|课程|github|网页",
                text,
                re.IGNORECASE,
            )
        )
    elif task == "semantic_complexity":
        if length >= 500 or re.search(
            r"深入|详细|架构|方案|权衡|证明|调研|多步骤|为什么|分析",
            text,
        ):
            candidate = "high"
        elif length <= 100:
            candidate = "low"
        else:
            candidate = "medium"
    else:
        candidate = "short" if length <= 120 else "long" if length >= 500 else "medium"
    return available.get(_label_key(candidate), majority)


def train_students(output_root: Path | str, seed: int) -> dict[str, object]:
    """Train three group-isolated TF-IDF logistic-regression students."""

    root = Path(output_root).expanduser().resolve()
    silver_path = _silver_path(root)
    examples = _load_examples(silver_path)
    train, test, train_groups, test_groups = _group_split(examples, seed)
    train_texts = [example.text for example in train]

    models: dict[str, str] = {}
    classes: dict[str, list[bool | int | float | str]] = {}
    model_kinds: dict[str, str] = {}
    fitted_models: dict[str, Any] = {}
    for task in TASKS:
        labels = [example.labels[task] for example in train]
        unique_labels = {_label_key(label) for label in labels}
        if len(unique_labels) < 2:
            model = DummyClassifier(strategy="most_frequent")
            model_kinds[task] = "constant_dummy_single_training_class"
        else:
            model = _new_model(seed)
            model_kinds[task] = "tfidf_logistic_regression"
        model.fit(train_texts, labels)
        fitted_models[task] = model

    model_directory = root / "students/models"
    model_directory.mkdir(parents=True, exist_ok=True)
    for task, model in fitted_models.items():
        path = _model_path(root, task)
        joblib.dump(model, path)
        models[task] = str(path)
        classes[task] = [_json_label(label) for label in model.classes_]

    split_path = root / "students/splits.json"
    split_report: dict[str, object] = {
        "schema_version": 1,
        "seed": seed,
        "strategy": "conversation_ref_group_80_20",
        "train": {
            "conversation_refs": train_groups,
            "window_ids": [example.window_id for example in train],
        },
        "test": {
            "conversation_refs": test_groups,
            "window_ids": [example.window_id for example in test],
        },
    }
    _write_json(split_path, split_report)

    report = {
        "schema_version": 1,
        "silver_path": str(silver_path),
        "sample_count": len(examples),
        "train_sample_count": len(train),
        "test_sample_count": len(test),
        "train_conversation_count": len(train_groups),
        "test_conversation_count": len(test_groups),
        "classes": classes,
        "model_kinds": model_kinds,
        "models": models,
        "splits_path": str(split_path),
    }
    training_path = root / "students/training.json"
    _write_json(training_path, report)
    return {**report, "training_path": str(training_path)}


def _load_models(output_root: Path) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for task in TASKS:
        path = _model_path(output_root, task)
        if not path.is_file():
            raise FileNotFoundError(path)
        models[task] = joblib.load(path)
    return models


def evaluate_students(output_root: Path | str) -> dict[str, object]:
    """Evaluate saved students on the held-out conversation groups."""

    root = Path(output_root).expanduser().resolve()
    silver_path = _silver_path(root)
    examples = _load_examples(silver_path)
    split_path = root / "students/splits.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    test_section = split.get("test")
    if not isinstance(test_section, Mapping):
        raise TypeError("students/splits.json is missing test split")
    raw_test_ids = test_section.get("window_ids")
    if not isinstance(raw_test_ids, list) or not all(
        isinstance(item, str) for item in raw_test_ids
    ):
        raise ValueError("students/splits.json test.window_ids must be strings")
    test_ids = set(raw_test_ids)
    test = [example for example in examples if example.window_id in test_ids]
    if len(test) != len(test_ids):
        found_ids = {example.window_id for example in test}
        missing = sorted(test_ids - found_ids)
        raise ValueError(f"test windows missing from Silver dataset: {missing[:10]}")
    if not test:
        raise ValueError("test split is empty")
    train_section = split.get("train")
    if not isinstance(train_section, Mapping):
        raise TypeError("students/splits.json is missing train split")
    raw_train_ids = train_section.get("window_ids")
    if not isinstance(raw_train_ids, list) or not all(
        isinstance(item, str) for item in raw_train_ids
    ):
        raise ValueError("students/splits.json train.window_ids must be strings")
    train_ids = set(raw_train_ids)
    train = [example for example in examples if example.window_id in train_ids]
    if not train:
        raise ValueError("train split is empty")

    models = _load_models(root)
    texts = [example.text for example in test]
    task_metrics: dict[str, object] = {}
    for task, model in models.items():
        expected = [example.labels[task] for example in test]
        predicted = model.predict(texts)
        train_labels = [example.labels[task] for example in train]
        majority_label = Counter(train_labels).most_common(1)[0][0]
        label_values = _unique_labels(
            list(model.classes_), expected, list(predicted)
        )
        class_names = [_label_key(label) for label in label_values]
        detailed = classification_report(
            expected,
            predicted,
            labels=label_values,
            target_names=class_names,
            output_dict=True,
            zero_division=0,
        )
        per_class = {
            class_name: {
                "precision": float(detailed[class_name]["precision"]),
                "recall": float(detailed[class_name]["recall"]),
                "f1": float(detailed[class_name]["f1-score"]),
                "support": int(detailed[class_name]["support"]),
            }
            for class_name in class_names
        }
        available = {
            _label_key(label): label for label in _unique_labels(train_labels, expected)
        }
        majority_predictions = [majority_label] * len(test)
        static_predictions = [
            _static_rule_label(task, example.text, available, majority_label)
            for example in test
        ]
        task_metrics[task] = {
            "sample_count": len(test),
            "coverage": 1.0,
            "abstain_count": 0,
            **_metric_bundle(expected, predicted, label_values),
            "confusion_matrix": {
                "labels": class_names,
                "rows": confusion_matrix(
                    expected, predicted, labels=label_values
                ).tolist(),
            },
            "per_class": per_class,
            "majority_baseline": {
                "label": _json_label(majority_label),
                **_metric_bundle(expected, majority_predictions, label_values),
            },
            "static_rule_baseline": _metric_bundle(
                expected, static_predictions, label_values
            ),
        }

    metrics: dict[str, object] = {
        "schema_version": 1,
        "silver_path": str(silver_path),
        "split_path": str(split_path),
        "metric_scope": "held_out_silver_agreement",
        "test_sample_count": len(test),
        "tasks": task_metrics,
    }
    metrics_path = root / "students/metrics.json"
    _write_json(metrics_path, metrics)
    return {**metrics, "metrics_path": str(metrics_path)}


def _predict_batch(
    models: Mapping[str, Any], windows: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    texts = [_window_text(window) for window in windows]
    task_predictions: dict[str, tuple[Sequence[object], Sequence[Sequence[float]]]] = {}
    for task, model in models.items():
        task_predictions[task] = (model.predict(texts), model.predict_proba(texts))

    output: list[dict[str, object]] = []
    for index, window in enumerate(windows):
        predictions: dict[str, object] = {}
        for task in TASKS:
            labels, probabilities = task_predictions[task]
            predictions[task] = {
                "label": _json_label(labels[index]),
                "confidence": float(max(probabilities[index])),
            }
        output.append(
            {
                "window_id": _required_string(
                    window.get("window_id"), "window.window_id"
                ),
                "conversation_ref": _required_string(
                    window.get("conversation_ref"), "window.conversation_ref"
                ),
                "predictions": predictions,
            }
        )
    return output


def predict_all(output_root: Path | str) -> dict[str, object]:
    """Stream all windows through saved students and write prediction JSONL."""

    root = Path(output_root).expanduser().resolve()
    input_path = root / "windows/all.jsonl"
    models = _load_models(root)
    output_path = root / "students/predictions.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch: list[Mapping[str, object]] = []
    prediction_count = 0
    distributions = {task: Counter[str]() for task in TASKS}

    with output_path.open("w", encoding="utf-8") as handle:
        for row in _read_jsonl(input_path):
            batch.append(_extract_window(row))
            if len(batch) < BATCH_SIZE:
                continue
            for prediction in _predict_batch(models, batch):
                handle.write(json.dumps(prediction, ensure_ascii=False) + "\n")
                prediction_count += 1
                values = prediction["predictions"]
                if isinstance(values, Mapping):
                    for task in TASKS:
                        task_value = values.get(task)
                        if isinstance(task_value, Mapping):
                            distributions[task][_label_key(task_value.get("label"))] += 1
            batch.clear()

        if batch:
            for prediction in _predict_batch(models, batch):
                handle.write(json.dumps(prediction, ensure_ascii=False) + "\n")
                prediction_count += 1
                values = prediction["predictions"]
                if isinstance(values, Mapping):
                    for task in TASKS:
                        task_value = values.get(task)
                        if isinstance(task_value, Mapping):
                            distributions[task][_label_key(task_value.get("label"))] += 1

    report = {
        "schema_version": 1,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "prediction_count": prediction_count,
        "batch_size": BATCH_SIZE,
        "label_distribution": {
            task: dict(sorted(counts.items())) for task, counts in distributions.items()
        },
    }
    summary_path = root / "students/prediction-summary.json"
    _write_json(summary_path, report)
    return {**report, "summary_path": str(summary_path)}
