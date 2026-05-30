import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re


_SUPPORTED_SUFFIXES = {".jsonl", ".json", ".csv", ".txt", ".md"}
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


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _iter_text_samples(dataset_path: Path) -> list[str]:
    samples: list[str] = []
    if dataset_path.is_file():
        files = [dataset_path]
    else:
        files = sorted([path for path in dataset_path.rglob("*") if path.is_file()])
    for file_path in files:
        suffix = file_path.suffix.lower()
        if suffix not in _SUPPORTED_SUFFIXES:
            continue
        if suffix in {".txt", ".md"}:
            text = _normalize_text(file_path.read_text(encoding="utf-8", errors="ignore"))
            if text:
                samples.append(text)
            continue
        if suffix == ".csv":
            with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    text = _normalize_text(" ".join(row))
                    if text:
                        samples.append(text)
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
            elif isinstance(item, dict):
                text = _normalize_text(str(item.get("text") or item.get("content") or ""))
                if text:
                    samples.append(text)
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


def prepare_ph_dataset_artifacts(dataset_path: Path, output_dir: Path) -> DatasetPrepResult:
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
        )
    raw_samples = _iter_text_samples(resolved_dataset)
    if not raw_samples:
        return DatasetPrepResult(
            accepted=False,
            reason="dataset_empty_or_unsupported",
            datasetPath=str(resolved_dataset),
            outputDir=str(output_dir.resolve()),
            rawSamples=0,
            trainSamples=0,
            valSamples=0,
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

    return DatasetPrepResult(
        accepted=True,
        reason="prepared",
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
    )
