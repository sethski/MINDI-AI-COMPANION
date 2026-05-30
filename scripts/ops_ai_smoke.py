from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AI smoke probes through the local agent and save a benchmark artifact."
    )
    parser.add_argument("--agent-url", default="http://127.0.0.1:8765", help="Agent base URL")
    parser.add_argument("--include-llm", action="store_true", default=True, help="Run LLM probe")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM probe")
    parser.add_argument("--include-asr", action="store_true", help="Run ASR probe")
    parser.add_argument("--include-ocr", action="store_true", help="Run OCR probe")
    parser.add_argument("--llm-prompt", default="Summarize this system status in one sentence.")
    parser.add_argument("--language-mode", choices=("english", "taglish", "tagalog"), default="english")
    parser.add_argument("--asr-file-path", default="", help="Path to local audio file for ASR probe")
    parser.add_argument("--asr-language-hint", default="", help="ASR language hint")
    parser.add_argument("--ocr-image-path", default="", help="Path to local image file for OCR probe")
    parser.add_argument(
        "--out-dir",
        default="data/runtime/benchmarks",
        help="Output directory for JSON benchmark artifacts",
    )
    return parser.parse_args()


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    include_llm = bool(args.include_llm and not args.skip_llm)
    payload: dict[str, object] = {
        "includeLlm": include_llm,
        "includeAsr": bool(args.include_asr),
        "includeOcr": bool(args.include_ocr),
        "llmPrompt": args.llm_prompt,
        "languageMode": args.language_mode,
    }
    if args.asr_file_path.strip():
        payload["asrFilePath"] = args.asr_file_path.strip()
    if args.asr_language_hint.strip():
        payload["asrLanguageHint"] = args.asr_language_hint.strip()
    if args.ocr_image_path.strip():
        payload["ocrImagePath"] = args.ocr_image_path.strip()
    return payload


def post_smoke(agent_url: str, payload: dict[str, object]) -> dict[str, object]:
    endpoint = f"{agent_url.rstrip('/')}/ops/ai/smoke"
    raw = json.dumps(payload).encode("utf-8")
    request = Request(
        endpoint,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=240) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach agent endpoint {endpoint}: {exc.reason}") from exc

    return json.loads(body)


def write_artifact(out_dir: Path, payload: dict[str, object], result: dict[str, object]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"ai_smoke_{stamp}.json"
    artifact = {
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "request": payload,
        "result": result,
    }
    target.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return target


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    result = post_smoke(args.agent_url, payload)
    artifact = write_artifact(Path(args.out_dir), payload, result)

    print(f"Saved smoke benchmark artifact: {artifact.resolve()}")
    print(f"accepted={result.get('accepted')} reason={result.get('reason')}")
    probes = result.get("probes", {})
    for feature in ("llm", "asr", "ocr"):
        probe = probes.get(feature, {})
        print(
            f"{feature}: attempted={probe.get('attempted')} accepted={probe.get('accepted')} "
            f"reason={probe.get('reason')} latencyMs={probe.get('latencyMs')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
