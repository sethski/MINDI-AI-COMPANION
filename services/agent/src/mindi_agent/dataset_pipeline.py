import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


_SUPPORTED_SUFFIXES = {".jsonl", ".json", ".csv", ".txt", ".md", ".parquet"}
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]{1,31}")


@dataclass
class DatasetPrepResult:
    accepted: bool
    reason: str
    datasetPath: str
    outputDir: str
    rawSamples: int
    trainSamples: int
    valSamples: int
    languagePackPath: str | None = None
    trainJsonlPath: str | None = None
    valJsonlPath: str | None = None
    configPath: str | None = None
    manifestPath: str | None = None
    validationPassed: bool = False
    validationIssues: list[str] | None = None


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _row_matches_filter(
    row: dict[str, Any],
    *,
    languages: list[str] | None = None,
    quality_buckets: list[str] | None = None,
) -> bool:
    normalized_languages = {item.strip().lower() for item in languages or [] if item.strip()}
    normalized_quality = {item.strip().lower() for item in quality_buckets or [] if item.strip()}
    if normalized_languages:
        language_value = str(
            row.get("language")
            or row.get("lang")
            or row.get("locale")
            or row.get("language_code")
            or ""
        ).strip().lower()
        if language_value and language_value not in normalized_languages:
            return False
        if not language_value:
            return False
    if normalized_quality:
        quality_value = str(
            row.get("quality")
            or row.get("quality_bucket")
            or row.get("qualityBucket")
            or row.get("bucket")
            or ""
        ).strip().lower()
        if quality_value and quality_value not in normalized_quality:
            return False
        if not quality_value:
            return False
    return True


def _extract_row_text(row: dict[str, Any]) -> str:
    for key in ("text", "content", "sentence", "body", "sample"):
        value = row.get(key)
        if value is not None:
            text = _normalize_text(str(value))
            if text:
                return text
    return _normalize_text(" ".join(str(value) for value in row.values() if value is not None))


def _iter_parquet_text_samples(
    file_path: Path,
    *,
    max_samples: int | None = None,
    languages: list[str] | None = None,
    quality_buckets: list[str] | None = None,
) -> list[str]:
    try:
        import pyarrow.parquet as parquet
    except ImportError:
        return []

    samples: list[str] = []
    table = parquet.read_table(file_path)
    for row in table.to_pylist():
        if not isinstance(row, dict):
            continue
        if not _row_matches_filter(row, languages=languages, quality_buckets=quality_buckets):
            continue
        text = _extract_row_text(row)
        if text:
            samples.append(text)
        if max_samples is not None and len(samples) >= max_samples:
            break
    return samples


def _iter_text_samples(
    dataset_path: Path,
    *,
    max_samples: int | None = None,
    languages: list[str] | None = None,
    quality_buckets: list[str] | None = None,
) -> list[str]:
    samples: list[str] = []
    if dataset_path.is_file():
        files = [dataset_path]
    else:
        files = sorted([path for path in dataset_path.rglob("*") if path.is_file()])
    for file_path in files:
        suffix = file_path.suffix.lower()
        if suffix not in _SUPPORTED_SUFFIXES:
            continue
        remaining = None if max_samples is None else max_samples - len(samples)
        if remaining is not None and remaining <= 0:
            break
        if suffix == ".parquet":
            samples.extend(
                _iter_parquet_text_samples(
                    file_path,
                    max_samples=remaining,
                    languages=languages,
                    quality_buckets=quality_buckets,
                )
            )
            continue
        if suffix in {".txt", ".md"}:
            text = _normalize_text(file_path.read_text(encoding="utf-8", errors="ignore"))
            if text:
                samples.append(text)
            if max_samples is not None and len(samples) >= max_samples:
                break
            continue
        if suffix == ".csv":
            with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    text = _normalize_text(" ".join(row))
                    if text:
                        samples.append(text)
                    if max_samples is not None and len(samples) >= max_samples:
                        break
            continue
        if suffix == ".jsonl":
            for raw in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    text = _normalize_text(str(item.get("text") or item.get("content") or ""))
                    if text:
                        samples.append(text)
                elif isinstance(item, str):
                    text = _normalize_text(item)
                    if text:
                        samples.append(text)
                if max_samples is not None and len(samples) >= max_samples:
                    break
            continue
        if suffix == ".json":
            try:
                item = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
            except json.JSONDecodeError:
                continue
            if isinstance(item, list):
                for entry in item:
                    if isinstance(entry, dict):
                        text = _normalize_text(str(entry.get("text") or entry.get("content") or ""))
                        if text:
                            samples.append(text)
                    elif isinstance(entry, str):
                        text = _normalize_text(entry)
                        if text:
                            samples.append(text)
                    if max_samples is not None and len(samples) >= max_samples:
                        break
            elif isinstance(item, dict):
                text = _normalize_text(str(item.get("text") or item.get("content") or ""))
                if text:
                    samples.append(text)
            if max_samples is not None and len(samples) >= max_samples:
                break
    return samples


def _stable_split(samples: list[str]) -> tuple[list[str], list[str]]:
    train: list[str] = []
    val: list[str] = []
    for sample in samples:
        digest = hashlib.sha1(sample.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 10
        if bucket == 0:
            val.append(sample)
        else:
            train.append(sample)
    if not train and val:
        train.append(val.pop(0))
    if not val and len(train) > 1:
        val.append(train.pop())
    return train, val


def _to_chat_row(text: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": "You are MINDI, a safe local assistant for Filipino users."},
            {"role": "user", "content": "Give a natural Taglish rewrite of this sentence."},
            {"role": "assistant", "content": text},
        ]
    }


def _validate_json_object(path: Path, required_keys: set[str]) -> tuple[dict[str, Any] | None, list[str]]:
    issues: list[str] = []
    if not path.exists() or not path.is_file():
        return None, [f"missing:{path.name}"]
    if path.stat().st_size == 0:
        return None, [f"empty:{path.name}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, [f"invalid_json:{path.name}"]
    if not isinstance(payload, dict):
        return None, [f"invalid_shape:{path.name}"]
    for key in sorted(required_keys):
        if key not in payload:
            issues.append(f"missing_key:{path.name}:{key}")
    return payload, issues


def _validate_chat_jsonl(path: Path, *, label: str) -> list[str]:
    issues: list[str] = []
    if not path.exists() or not path.is_file():
        return [f"missing:{label}"]
    if path.stat().st_size == 0:
        return [f"empty:{label}"]
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return [f"empty:{label}"]
    for index, line in enumerate(lines):
        if not line.strip():
            issues.append(f"blank_line:{label}:{index + 1}")
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            issues.append(f"invalid_jsonl:{label}:{index + 1}")
            continue
        if not isinstance(payload, dict):
            issues.append(f"invalid_row_shape:{label}:{index + 1}")
            continue
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) < 3:
            issues.append(f"invalid_messages:{label}:{index + 1}")
            continue
    return issues


def _validate_artifacts(
    *,
    dataset_path: Path,
    output_dir: Path,
    language_pack: Path,
    train_jsonl: Path,
    val_jsonl: Path,
    config: Path,
    manifest: Path,
) -> list[str]:
    issues: list[str] = []
    issues.extend(_validate_chat_jsonl(train_jsonl, label="train_jsonl"))
    issues.extend(_validate_chat_jsonl(val_jsonl, label="val_jsonl"))

    language_pack_payload, pack_issues = _validate_json_object(
        language_pack,
        {"languageModeDefault", "sourceDataset", "sampleCount", "topTerms"},
    )
    issues.extend(pack_issues)
    if isinstance(language_pack_payload, dict):
        if str(language_pack_payload.get("sourceDataset", "")) != str(dataset_path):
            issues.append("source_dataset_mismatch:language_pack")
        if not isinstance(language_pack_payload.get("topTerms"), list):
            issues.append("invalid_top_terms:language_pack")

    config_payload, config_issues = _validate_json_object(
        config,
        {"baseModel", "method", "dataset", "training", "targetHardware", "executionScope"},
    )
    issues.extend(config_issues)
    if isinstance(config_payload, dict):
        dataset_payload = config_payload.get("dataset")
        if not isinstance(dataset_payload, dict):
            issues.append("invalid_dataset_block:config")
        else:
            if str(dataset_payload.get("trainJsonl", "")) != str(train_jsonl):
                issues.append("train_path_mismatch:config")
            if str(dataset_payload.get("valJsonl", "")) != str(val_jsonl):
                issues.append("val_path_mismatch:config")

    manifest_payload, manifest_issues = _validate_json_object(
        manifest,
        {"accepted", "reason", "datasetPath", "outputDir", "artifacts", "validation"},
    )
    issues.extend(manifest_issues)
    if isinstance(manifest_payload, dict):
        if str(manifest_payload.get("datasetPath", "")) != str(dataset_path):
            issues.append("dataset_path_mismatch:manifest")
        if str(manifest_payload.get("outputDir", "")) != str(output_dir):
            issues.append("output_dir_mismatch:manifest")
        artifacts_payload = manifest_payload.get("artifacts")
        if not isinstance(artifacts_payload, dict):
            issues.append("invalid_artifacts_block:manifest")
        else:
            if str(artifacts_payload.get("languagePackPath", "")) != str(language_pack):
                issues.append("language_pack_path_mismatch:manifest")
            if str(artifacts_payload.get("trainJsonlPath", "")) != str(train_jsonl):
                issues.append("train_path_mismatch:manifest")
            if str(artifacts_payload.get("valJsonlPath", "")) != str(val_jsonl):
                issues.append("val_path_mismatch:manifest")
            if str(artifacts_payload.get("configPath", "")) != str(config):
                issues.append("config_path_mismatch:manifest")
    return issues


def prepare_ph_dataset_artifacts(
    dataset_path: Path,
    output_dir: Path,
    *,
    max_samples: int | None = None,
    languages: list[str] | None = None,
    quality_buckets: list[str] | None = None,
) -> DatasetPrepResult:
    resolved_dataset = dataset_path.resolve()
    if not resolved_dataset.exists():
        return DatasetPrepResult(
            accepted=False,
            reason="dataset_not_found",
            datasetPath=str(resolved_dataset),
            outputDir=str(output_dir.resolve()),
            rawSamples=0,
            trainSamples=0,
            valSamples=0,
            validationPassed=False,
            validationIssues=["dataset_not_found"],
        )
    raw_samples = _iter_text_samples(
        resolved_dataset,
        max_samples=max_samples,
        languages=languages,
        quality_buckets=quality_buckets,
    )
    if not raw_samples:
        return DatasetPrepResult(
            accepted=False,
            reason="dataset_empty_or_unsupported",
            datasetPath=str(resolved_dataset),
            outputDir=str(output_dir.resolve()),
            rawSamples=0,
            trainSamples=0,
            valSamples=0,
            validationPassed=False,
            validationIssues=["dataset_empty_or_unsupported"],
        )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    train, val = _stable_split(raw_samples)

    train_jsonl = output_dir / "qwen2p5_train.jsonl"
    val_jsonl = output_dir / "qwen2p5_val.jsonl"
    language_pack = output_dir / "language_pack_ph.json"
    config = output_dir / "qwen2p5_finetune_config.json"
    manifest = output_dir / "run_manifest.json"

    with train_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in train:
            handle.write(json.dumps(_to_chat_row(sample), ensure_ascii=True) + "\n")
    with val_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in val:
            handle.write(json.dumps(_to_chat_row(sample), ensure_ascii=True) + "\n")

    words = Counter()
    for sample in raw_samples:
        for token in _WORD_PATTERN.findall(sample):
            words[token.lower()] += 1
    common_terms = [term for term, _ in words.most_common(250)]
    language_pack_payload = {
        "languageModeDefault": "taglish",
        "sourceDataset": str(resolved_dataset),
        "sampleCount": len(raw_samples),
        "topTerms": common_terms,
        "notes": [
            "Prompt/style adaptation artifact for Filipino language support.",
            "Does not include model weights.",
        ],
    }
    language_pack.write_text(json.dumps(language_pack_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    config_payload = {
        "baseModel": "Qwen/Qwen2.5-7B-Instruct",
        "method": "lora",
        "dataset": {
            "trainJsonl": str(train_jsonl),
            "valJsonl": str(val_jsonl),
            "format": "chatml_messages",
        },
        "training": {
            "epochs": 2,
            "learningRate": 2e-4,
            "batchSize": 1,
            "gradientAccumulationSteps": 8,
            "maxSeqLen": 2048,
        },
        "targetHardware": "cpu_only",
        "executionScope": "prep_and_train_interface",
    }
    config.write_text(json.dumps(config_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    manifest_payload = {
        "accepted": True,
        "reason": "prepared",
        "datasetPath": str(resolved_dataset),
        "outputDir": str(output_dir),
        "rawSamples": len(raw_samples),
        "trainSamples": len(train),
        "valSamples": len(val),
        "artifacts": {
            "languagePackPath": str(language_pack),
            "trainJsonlPath": str(train_jsonl),
            "valJsonlPath": str(val_jsonl),
            "configPath": str(config),
        },
        "validation": {
            "trainExists": train_jsonl.exists(),
            "valExists": val_jsonl.exists(),
            "languagePackExists": language_pack.exists(),
            "configExists": config.exists(),
        },
    }
    manifest.write_text(json.dumps(manifest_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    validation_issues = _validate_artifacts(
        dataset_path=resolved_dataset,
        output_dir=output_dir,
        language_pack=language_pack,
        train_jsonl=train_jsonl,
        val_jsonl=val_jsonl,
        config=config,
        manifest=manifest,
    )
    accepted = len(validation_issues) == 0
    reason = "prepared" if accepted else "artifact_validation_failed"

    return DatasetPrepResult(
        accepted=accepted,
        reason=reason,
        datasetPath=str(resolved_dataset),
        outputDir=str(output_dir),
        rawSamples=len(raw_samples),
        trainSamples=len(train),
        valSamples=len(val),
        languagePackPath=str(language_pack),
        trainJsonlPath=str(train_jsonl),
        valJsonlPath=str(val_jsonl),
        configPath=str(config),
        manifestPath=str(manifest),
        validationPassed=accepted,
        validationIssues=validation_issues,
    )
