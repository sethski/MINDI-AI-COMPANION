export type MindiInputKind =
  | "selection"
  | "clipboard_summarize"
  | "clipboard_translate"
  | "clipboard_explain";

export interface MindiInputPayload {
  kind: MindiInputKind;
  text: string;
}

export function buildInputPrompt(kind: MindiInputKind, text: string): string {
  const trimmed = text.trim();
  switch (kind) {
    case "selection":
      return trimmed;
    case "clipboard_summarize":
      return `Summarize the following text concisely:\n\n${trimmed}`;
    case "clipboard_translate":
      return `Translate the following text to English (or Tagalog if it is already English). Keep the tone natural:\n\n${trimmed}`;
    case "clipboard_explain":
      return `Explain the following text in plain language:\n\n${trimmed}`;
    default:
      return trimmed;
  }
}

const IMAGE_EXT = ["png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"];
const DOC_EXT = ["pdf", "txt", "md", "markdown", "rtf", "doc", "docx", "csv", "json"];

export function classifyDroppedPath(path: string): "image" | "document" | "unsupported" {
  const dot = path.lastIndexOf(".");
  const ext = dot >= 0 ? path.slice(dot + 1).toLowerCase() : "";
  if (IMAGE_EXT.includes(ext)) {
    return "image";
  }
  if (DOC_EXT.includes(ext)) {
    return "document";
  }
  return "unsupported";
}
