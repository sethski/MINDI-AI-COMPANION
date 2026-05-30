from __future__ import annotations

import argparse
import json
from pathlib import Path


def _normalize_ocr_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
    return cleaned


def _extract_generated_text(payload: object) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        role = str(payload.get("role", "")).strip().lower()
        if role == "assistant":
            return _extract_generated_text(payload.get("content"))
        if "generated_text" in payload:
            return _extract_generated_text(payload.get("generated_text"))
        if "content" in payload:
            return _extract_generated_text(payload.get("content"))
        if "text" in payload:
            return _extract_generated_text(payload.get("text"))
        return ""
    if isinstance(payload, list):
        assistant_items = [
            item for item in payload if isinstance(item, dict) and str(item.get("role", "")).strip().lower() == "assistant"
        ]
        if assistant_items:
            return _extract_generated_text(assistant_items[-1])
        chunks = [_extract_generated_text(item) for item in payload]
        filtered = [chunk for chunk in chunks if chunk]
        return "\n".join(filtered).strip()
    return str(payload).strip()


def _run(model_ref: str, image_path: str, max_new_tokens: int) -> dict:
    from transformers import AutoModelForImageTextToText, AutoProcessor

    source = Path(image_path).resolve()
    if not source.exists() or not source.is_file():
        return {"accepted": False, "reason": "image_not_found"}

    try:
        processor = AutoProcessor.from_pretrained(model_ref)
        model = AutoModelForImageTextToText.from_pretrained(
            pretrained_model_name_or_path=model_ref,
            torch_dtype="auto",
            device_map="auto",
        )
    except Exception as exc:
        return {"accepted": False, "reason": "ocr_model_load_failed", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "url": str(source)},
                {"type": "text", "text": "Text Recognition:"},
            ],
        }
    ]
    try:
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)
        inputs.pop("token_type_ids", None)
        generated_ids = model.generate(**inputs, max_new_tokens=max(128, int(max_new_tokens)))
        output_text = processor.decode(generated_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=False)
    except Exception as exc:
        return {"accepted": False, "reason": "ocr_inference_failed", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}

    text = _normalize_ocr_text(_extract_generated_text(output_text))
    if not text:
        return {"accepted": False, "reason": "ocr_no_text_detected"}
    return {
        "accepted": True,
        "reason": "ok",
        "text": text,
        "ocrMode": "glm_ocr_markdown",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GLM-OCR helper")
    parser.add_argument("--model-ref", required=True)
    parser.add_argument("--image-path", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    args = parser.parse_args()

    payload = _run(args.model_ref, args.image_path, args.max_new_tokens)
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
