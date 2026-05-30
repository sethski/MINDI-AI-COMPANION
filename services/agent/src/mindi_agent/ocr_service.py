from pathlib import Path


def extract_text_for_ocr(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path), "pdf_text_layer"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}:
        return _extract_image_text(path), "image_ocr"
    raise ValueError("ocr_unsupported_file_type")


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover
        raise ValueError("ocr_dependencies_missing") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            parts.append(text)
    merged = "\n".join(parts).strip()
    if not merged:
        raise ValueError("pdf_text_not_found")
    return merged


def _extract_image_text(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise ValueError("ocr_dependencies_missing") from exc

    try:
        text = pytesseract.image_to_string(Image.open(path))
    except pytesseract.TesseractNotFoundError as exc:
        raise ValueError("tesseract_not_installed") from exc
    except Exception as exc:  # pragma: no cover
        raise ValueError("ocr_failed") from exc

    text = text.strip()
    if not text:
        raise ValueError("ocr_no_text_detected")
    return text
