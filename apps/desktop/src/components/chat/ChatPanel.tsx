import { useCallback, useEffect, useId, useRef, useState } from "react";
import { importDocument, importOcrDocument, sendAssistantRequest } from "../../lib/agent-api";
import { enqueueSyncItem, loadSyncQueue } from "../../lib/local-state";
import { isTauriRuntime, saveUploadTemp } from "../../lib/tauri-window";

type ChatRole = "user" | "assistant";
type TurnState = "sending" | "ok" | "error";

interface ChatTurn {
  id: string;
  role: ChatRole;
  content: string;
  ts: number;
  state: TurnState;
  meta?: string;
}

interface ChatPanelProps {
  online: boolean;
  onSyncDepthChange?: (depth: number) => void;
}

const SUGGESTIONS = [
  "Summarize my open tasks",
  "What can you help me with?",
  "Draft a reminder for tomorrow 9am",
] as const;

const IMAGE_EXT = ["png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"];
const DOC_EXT = ["pdf", "txt", "md", "markdown", "rtf", "doc", "docx", "csv", "json"];

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatTime(ts: number): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error("file_read_failed"));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error("file_read_failed"));
    reader.readAsDataURL(file);
  });
}

function PaperclipGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path
        d="M18.4 11.5 12 17.9a4 4 0 0 1-5.7-5.7l7-7a2.6 2.6 0 0 1 3.7 3.7l-7 7a1.2 1.2 0 0 1-1.7-1.7l6.2-6.2"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SendGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path
        d="M4.5 12 19 5l-4 14-3.6-5.4L4.5 12Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ChatPanel({ online, onSyncDepthChange }: ChatPanelProps) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const inputId = useId();

  useEffect(() => {
    const node = threadRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [turns]);

  const appendTurn = useCallback((turn: ChatTurn) => {
    setTurns((current) => [...current, turn]);
  }, []);

  const patchTurn = useCallback((id: string, patch: Partial<ChatTurn>) => {
    setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));
  }, []);

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) {
        return;
      }

      setBusy(true);
      appendTurn({ id: newId(), role: "user", content: trimmed, ts: Date.now(), state: "ok" });
      const replyId = newId();
      appendTurn({ id: replyId, role: "assistant", content: "", ts: Date.now(), state: "sending" });

      try {
        const response = await sendAssistantRequest({ text: trimmed, mode: "chat", tab: "home" });
        const degraded = Boolean(response.degraded);
        const provider = response.provider ? `${response.provider}` : undefined;
        const model = response.model ? ` · ${response.model}` : "";
        patchTurn(replyId, {
          content:
            response.reply?.trim() ||
            (degraded
              ? `Local model unavailable (${response.fallbackReason ?? "runtime_error"}).`
              : "I am ready when you are."),
          state: degraded ? "error" : "ok",
          meta: degraded
            ? `degraded: ${response.fallbackReason ?? "runtime_error"}`
            : provider
              ? `${provider}${model}`
              : undefined,
        });
      } catch {
        enqueueSyncItem({ type: "chat", payload: { text: trimmed, mode: "chat", tab: "home" } });
        onSyncDepthChange?.(loadSyncQueue().length);
        patchTurn(replyId, {
          content: "I could not reach the local agent, so I queued this and will sync when it is back.",
          state: "error",
          meta: "agent_unreachable",
        });
      } finally {
        setBusy(false);
      }
    },
    [appendTurn, busy, onSyncDepthChange, patchTurn],
  );

  const handleSubmit = useCallback(() => {
    void sendText(draft);
    setDraft("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [draft, sendText]);

  const handleUpload = useCallback(
    async (file: File) => {
      const ext = fileExtension(file.name);
      const isImage = file.type.startsWith("image/") || IMAGE_EXT.includes(ext);
      const isDoc = DOC_EXT.includes(ext) || file.type === "application/pdf" || file.type.startsWith("text/");

      appendTurn({
        id: newId(),
        role: "user",
        content: `Uploaded ${file.name}`,
        ts: Date.now(),
        state: "ok",
        meta: `${(file.size / 1024).toFixed(0)} KB`,
      });
      const replyId = newId();
      appendTurn({ id: replyId, role: "assistant", content: "", ts: Date.now(), state: "sending" });

      if (!isTauriRuntime()) {
        patchTurn(replyId, {
          content: "File upload is only available in the MINDI desktop app, not in the browser preview.",
          state: "error",
          meta: "browser_unsupported",
        });
        return;
      }

      if (!isImage && !isDoc) {
        patchTurn(replyId, {
          content:
            "That file type is not supported yet. I can read images (OCR) and documents (PDF, TXT, MD, DOCX, CSV). Video and audio files are not supported yet.",
          state: "error",
          meta: "unsupported_type",
        });
        return;
      }

      try {
        const dataUrl = await fileToDataUrl(file);
        const path = await saveUploadTemp(dataUrl, file.name);
        if (isImage) {
          const result = await importOcrDocument(path);
          if (result.accepted) {
            patchTurn(replyId, {
              content: `Read "${file.name}" with OCR and saved it to memory${
                result.document?.title ? ` as "${result.document.title}"` : ""
              }. Ask me about its contents.`,
              state: "ok",
              meta: result.ocrModel ? `ocr · ${result.ocrModel}` : "ocr",
            });
          } else {
            patchTurn(replyId, {
              content: `Could not OCR "${file.name}". Reason: ${result.fallbackReason ?? result.reason}. Confirm the AI runtime and OCR model are configured in Settings.`,
              state: "error",
              meta: result.reason,
            });
          }
        } else {
          const result = await importDocument(path);
          if (result.accepted) {
            patchTurn(replyId, {
              content: `Imported "${file.name}" into memory${
                result.document?.title ? ` as "${result.document.title}"` : ""
              }. Ask me about its contents.`,
              state: "ok",
              meta: "document",
            });
          } else {
            patchTurn(replyId, {
              content: `Could not import "${file.name}". Reason: ${result.reason}.`,
              state: "error",
              meta: result.reason,
            });
          }
        }
      } catch (error) {
        patchTurn(replyId, {
          content: `Upload failed: ${error instanceof Error ? error.message : "unknown_error"}.`,
          state: "error",
          meta: "upload_failed",
        });
      }
    },
    [appendTurn, patchTurn],
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files) {
        return;
      }
      for (const file of Array.from(files)) {
        void handleUpload(file);
      }
    },
    [handleUpload],
  );

  const hasTurns = turns.length > 0;

  return (
    <section className="chat" aria-label="MINDI conversation">
      <header className="chat__bar">
        <div>
          <h2 className="chat__title">Chat</h2>
          <p className="chat__subtitle">
            {online ? "Connected to the local agent" : "Agent offline. Messages queue and sync later."}
          </p>
        </div>
        <span className={`chat__status chat__status--${online ? "online" : "offline"}`}>
          <span className="chat__status-dot" aria-hidden="true" />
          {online ? "Online" : "Offline"}
        </span>
      </header>

      <div
        className="chat__thread"
        ref={threadRef}
        role="log"
        aria-live="polite"
        aria-busy={busy}
      >
        {!hasTurns ? (
          <div className="chat__empty">
            <div className="chat__empty-mark" aria-hidden="true">
              MINDI
            </div>
            <h3 className="chat__empty-title">Start a conversation</h3>
            <p className="chat__empty-text">
              Ask a question, paste text, or attach a document or image. Replies come from the local
              Qwen model when the AI runtime is configured.
            </p>
            <div className="chat__suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="chat__chip"
                  onClick={() => {
                    setDraft(suggestion);
                    textareaRef.current?.focus();
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul className="chat__messages">
            {turns.map((turn) => (
              <li
                key={turn.id}
                className={`chat__msg chat__msg--${turn.role} ${
                  turn.state === "error" ? "chat__msg--error" : ""
                }`}
              >
                <div className="chat__msg-head">
                  <span className="chat__msg-role">{turn.role === "user" ? "You" : "MINDI"}</span>
                  <span className="chat__msg-time">{formatTime(turn.ts)}</span>
                </div>
                {turn.state === "sending" ? (
                  <div className="chat__typing" aria-label="MINDI is thinking">
                    <span />
                    <span />
                    <span />
                  </div>
                ) : (
                  <p className="chat__msg-body">{turn.content}</p>
                )}
                {turn.meta ? <span className="chat__msg-meta">{turn.meta}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <form
        className="chat__composer"
        onSubmit={(event) => {
          event.preventDefault();
          handleSubmit();
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          Message MINDI
        </label>
        <input
          ref={fileInputRef}
          type="file"
          className="sr-only"
          accept="image/*,.pdf,.txt,.md,.markdown,.rtf,.doc,.docx,.csv,.json"
          multiple
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className="chat__icon-btn"
          aria-label="Attach a document or image"
          title="Attach a document or image"
          onClick={() => fileInputRef.current?.click()}
        >
          <PaperclipGlyph />
        </button>
        <textarea
          id={inputId}
          ref={textareaRef}
          className="chat__input"
          value={draft}
          placeholder="Message MINDI..."
          rows={1}
          onChange={(event) => {
            setDraft(event.target.value);
            const el = event.target;
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSubmit();
            }
          }}
        />
        <button
          type="submit"
          className="chat__send"
          aria-label="Send message"
          disabled={busy || draft.trim().length === 0}
        >
          <SendGlyph />
        </button>
      </form>
    </section>
  );
}
