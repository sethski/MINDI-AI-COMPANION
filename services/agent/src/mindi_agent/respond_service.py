"""LLM response pipeline: policy gate, RAG retrieval, style post-processing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    ActionLogItem,
    ActionTier,
    AssistantRequest,
    AssistantResponse,
    ChatMessage,
    ExecutedAction,
    IntelligenceTuningConfig,
    MemoryDocumentChunk,
    PolicyDecision,
    RagTrace,
    now_iso,
)
from .action_router import ActionRouter, ActionRouteResult
from uuid import uuid4

_LLM_FALLBACK_REPLY = (
    "I am here but my language model is not loaded yet. "
    "Open the AI Runtime panel to configure and start it."
)

_LLM_UNAVAILABLE_REPLIES: dict[str, str] = {
    "model_path_missing": (
        "No local model is configured. Open Settings > AI Runtime and point MINDI to a GGUF model file."
    ),
    "ollama_model_missing": (
        "The Ollama model is not pulled yet. Run `ollama pull <model>` in your terminal, then retry."
    ),
    "runtime_unreachable": (
        "The AI Runtime service is not running. Start it from the MINDI launcher or terminal."
    ),
}


class RespondService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store
        self._action_router = ActionRouter(store)

    def _should_try_action_route(self, request: AssistantRequest) -> bool:
        if request.wakeInvoke:
            return False
        if not (request.text or "").strip():
            return False
        return request.mode == "action" or not self.is_casual_chat_request(request.text)

    def _route_action(self, request: AssistantRequest) -> ActionRouteResult | None:
        if not self._should_try_action_route(request):
            return None
        plan = self._action_router.classify(request.text)
        if plan is None:
            return None
        return self._action_router.execute(plan, original_text=request.text)

    @staticmethod
    def _serialize_executed_actions(actions: list[ExecutedAction]) -> list[dict]:
        return [action.model_dump() for action in actions]

    def _resolve_conversation(self, request: AssistantRequest) -> list[ChatMessage]:
        if request.conversation:
            return request.conversation[-12:]
        rows = self._store.memory_db.list_chat_messages(limit=12)
        return [
            ChatMessage(role=row["role"], content=row["content"], timestamp=row["ts"])
            for row in rows
            if row["role"] in {"user", "assistant"}
        ]

    @staticmethod
    def _format_conversation_context(messages: list[ChatMessage]) -> str:
        if not messages:
            return ""
        blocks = [
            f"<{message.role}>{message.content}</{message.role}>"
            for message in messages
            if message.content.strip()
        ]
        if not blocks:
            return ""
        return "Recent conversation:\n" + "\n".join(blocks)

    def _with_conversation(self, prompt: str, request: AssistantRequest) -> str:
        context = self._format_conversation_context(self._resolve_conversation(request))
        if not context:
            return prompt
        return f"{context}\n\n{prompt}"

    def _should_persist_chat(self, request: AssistantRequest) -> bool:
        if request.wakeInvoke:
            return False
        return bool((request.text or "").strip()) and (request.mode or "chat") == "chat"

    def _persist_chat_turn(self, request: AssistantRequest, reply: str, meta: str | None = None) -> None:
        if not self._should_persist_chat(request):
            return
        self._store.append_chat_turn(
            user_text=request.text,
            assistant_text=reply,
            meta=meta,
        )

    def policy_decision(
        self,
        request: AssistantRequest,
        config: IntelligenceTuningConfig | None = None,
    ) -> PolicyDecision:
        active_config = config or self._store._active_tuning_config()
        text = request.text.lower()
        risky_terms = self._store._normalized_risky_terms(active_config)
        if any(term in text for term in risky_terms):
            return PolicyDecision(
                allowed=False,
                tier=ActionTier.risky,
                reason="requires_confirmation_or_unlock",
                requiresUnlock=True,
            )
        return PolicyDecision(
            allowed=True,
            tier=ActionTier.read_only,
            reason="safe_read_or_chat",
            requiresUnlock=False,
        )

    def _build_wake_invoke_prompt(self) -> str:
        hub = self._store.snapshot()
        open_tasks = [task for task in hub.tasks if task.status != "done"][:6]
        task_lines = (
            "\n".join(
                f"- {task.title} ({task.status})" + (f", due {task.dueAt}" if task.dueAt else "")
                for task in open_tasks
            )
            or "- No open tasks."
        )
        alert_lines = (
            "\n".join(f"- [{alert.severity}] {alert.title}: {alert.detail}" for alert in hub.alerts[:4])
            or "- No active alerts."
        )
        perception = self._store.memory_db.latest_perception_snapshot()
        perception_line = ""
        if perception is not None and (perception.text or "").strip():
            perception_line = f"Latest screen capture summary: {(perception.text or '').strip()[:400]}"
        recent_logs = (
            "\n".join(f"- {log.intent} ({log.result})" for log in hub.logs[:4]) or "- No recent actions."
        )
        return (
            "The user just called your name MINDI, like picking up a voice call. "
            "They did not ask a specific question -- decide what is most useful right now.\n"
            "Respond in 1-3 short spoken sentences. Greet them, surface the highest-value insight "
            "from context below, and offer one concrete next step. Sound natural on a call.\n"
            "Do not say you did not catch them or ask them to repeat themselves.\n\n"
            f"Open tasks:\n{task_lines}\n\n"
            f"Alerts:\n{alert_lines}\n\n"
            f"Recent activity:\n{recent_logs}\n\n"
            f"{perception_line}"
        ).strip()

    @staticmethod
    def is_casual_chat_request(text: str) -> bool:
        trimmed = text.strip().lower()
        if not trimmed:
            return False
        normalized = re.sub(r"[^a-z0-9\s]", " ", trimmed)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return False
        casual_phrases = {
            "hi", "hello", "hey", "yo", "sup",
            "good morning", "good afternoon", "good evening",
            "how are you", "how are you doing",
            "whats up", "what s up",
            "are you there", "you there",
            "thanks", "thank you", "ok", "okay",
        }
        if normalized in casual_phrases:
            return True
        words = normalized.split()
        if len(words) <= 4 and all(
            word in {"hi", "hello", "hey", "yo", "sup", "thanks", "thank", "you", "ok", "okay"}
            for word in words
        ):
            return True
        action_terms = {
            "task", "note", "file", "document", "screen", "calendar",
            "open", "delete", "create", "import", "export", "summarize", "search", "find", "scan",
        }
        if len(words) <= 5 and not any(word in action_terms for word in words):
            return True
        return False

    def _style_reply(
        self,
        reply: str,
        *,
        decision: PolicyDecision,
        config: IntelligenceTuningConfig | None = None,
        language_mode: str | None = None,
        slang_enabled: bool | None = None,
        slang_terms: list[str] | None = None,
    ) -> str:
        text = reply
        active_config = config or self._store._active_tuning_config()
        if active_config.responseVerbosity == "brief":
            first_sentence = text.split(". ", 1)[0].strip()
            text = first_sentence if first_sentence.endswith(".") else f"{first_sentence}."
        elif active_config.responseVerbosity == "detailed":
            if decision.allowed:
                text = f"{text} Audit trail is active for this step."
            else:
                text = f"{text} Safety policy is still enforced."
        if active_config.preset == "companion":
            text = f"{text} I can stay with you for the next step."
        effective_language_mode = language_mode or self._store.intelligence_language_mode
        effective_slang_enabled = (
            self._store.intelligence_slang_enabled if slang_enabled is None else bool(slang_enabled)
        )
        effective_slang_terms = self._store.intelligence_slang_terms if slang_terms is None else slang_terms
        if effective_language_mode == "taglish":
            text = f"Sige. {text}"
        elif effective_language_mode == "tagalog":
            text = f"Naiintindihan ko. {text}"
        if effective_slang_enabled and effective_slang_terms:
            text = f"{text} [{effective_slang_terms[0]}]"
        return text

    def respond(self, request: AssistantRequest) -> AssistantResponse:
        if not self._store.respond_lock.acquire(blocking=False):
            busy_decision = PolicyDecision(
                allowed=True, tier=ActionTier.read_only,
                reason="assistant_busy", requiresUnlock=False,
            )
            return AssistantResponse(
                reply="I am still working on your last message. Wait a moment, then try again.",
                decision=busy_decision,
                suggestedActions=["Wait", "Try again"],
                status="busy",
                provider="rule_local",
                model="busy_guard",
                degraded=True,
                fallbackReason="assistant_busy",
            )
        try:
            return self._respond_unlocked(request)
        finally:
            self._store.respond_lock.release()

    def _respond_unlocked(self, request: AssistantRequest) -> AssistantResponse:
        tuning = self._store._active_tuning_config()
        decision = self.policy_decision(request, config=tuning)
        result = "allowed" if decision.allowed else "blocked"
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()), intent=request.text,
                tier=decision.tier, result=result, reason=decision.reason, createdAt=now_iso(),
            ),
        )
        provider = "rule_local"
        model = "fallback"
        degraded = False
        fallback_reason: str | None = None
        citations: list[dict] = []
        rag_trace: dict = {"retrievalMode": "none", "confidence": 0.0, "fallbackReason": None}

        if decision.allowed:
            action_result = self._route_action(request)
            if action_result and action_result.handled and action_result.immediate:
                reply = self._style_reply(action_result.reply, decision=decision, config=tuning)
                return AssistantResponse(
                    reply=reply,
                    decision=decision,
                    suggestedActions=["Show status", "Scan files", "Open dashboard"],
                    status="ready",
                    provider="action_router",
                    model="local_rules",
                    executedActions=action_result.executed_actions,
                    citations=action_result.citations,
                )

            if request.wakeInvoke:
                llm_prompt = self._build_wake_invoke_prompt()
                llm_result = self._store.ai_runtime.generate_reply(
                    prompt=llm_prompt, language_mode=self._store.intelligence_language_mode,
                    llm_mode="voice",
                )
                if llm_result.get("accepted"):
                    reply = str(llm_result.get("reply") or llm_result.get("response") or "").strip()
                    if not reply:
                        reply = "I am here. What should we tackle first?"
                    provider = str(llm_result.get("provider") or "llama.cpp")
                    model = str(llm_result.get("model") or "Qwen/Qwen2.5-7B-Instruct")
                else:
                    reason = str(llm_result.get("reason") or "runtime_unavailable")
                    reply = _LLM_UNAVAILABLE_REPLIES.get(reason, _LLM_FALLBACK_REPLY)
                    provider = str(llm_result.get("provider") or "llama.cpp")
                    model = str(llm_result.get("model") or "fallback")
                    degraded = True
                    fallback_reason = reason
                reply = self._style_reply(reply, decision=decision, config=tuning)
                return AssistantResponse(
                    reply=reply, decision=decision, suggestedActions=["Open dashboard", "Review tasks", "Check status"],
                    status="ready", provider=provider, model=model, degraded=degraded, fallbackReason=fallback_reason,
                    citations=[], rag=RagTrace(retrievalMode="none", confidence=0.0, fallbackReason="wake_invoke"),
                )

            latest_snapshot = self._store.memory_db.latest_perception_snapshot()
            lowered = (request.text or "").lower()
            asks_about_screen = any(
                term in lowered
                for term in ("screen", "vision", "display", "what do you see", "what's on screen", "ocr")
            )
            if asks_about_screen and latest_snapshot is not None:
                snippet = (latest_snapshot.text or "").strip()
                summary = snippet[:220] if snippet else "No OCR text available."
                reply = (
                    "Latest perception snapshot available. "
                    f"Captured at {latest_snapshot.createdAt}, blocks={latest_snapshot.blockCount}, "
                    f"textLength={latest_snapshot.textLength}. Summary: {summary}"
                )
                provider = "memory_snapshot"
                model = "latest_perception_context"
            else:
                rag_items: list[MemoryDocumentChunk] = []
                if not self.is_casual_chat_request(request.text):
                    rag_items = self._store.memory_db.search_documents(query=request.text, limit=3)
                if rag_items and self._store._should_attach_document_rag(request.text, rag_items):
                    retrieval_mode = self._store._document_retrieval_mode(rag_items)
                    confidence = self._store._document_retrieval_confidence(rag_items)
                    rag_trace = {"retrievalMode": retrieval_mode, "confidence": confidence, "fallbackReason": None}
                    citations = [
                        {
                            "chunkId": item.id, "documentId": item.documentId, "sourcePath": item.sourcePath,
                            "title": item.title, "chunkIndex": item.chunkIndex, "score": item.score,
                            "textPreview": item.text[:240],
                        }
                        for item in rag_items
                    ]
                    context_blocks = [
                        "\n".join([f"Source {i}: {item.title}", f"Path: {item.sourcePath}", f"Excerpt: {item.text[:900]}"])
                        for i, item in enumerate(rag_items, start=1)
                    ]
                    llm_prompt = (
                        "Answer using the local source context when it is relevant. "
                        "Do not invent citations. If the context is weak, say what is missing.\n\n"
                        + "\n\n".join(context_blocks)
                        + f"\n\n<user_turn>{request.text}</user_turn>"
                    )
                else:
                    llm_prompt = f"<user_turn>{request.text}</user_turn>"
                    rag_trace = {"retrievalMode": "none", "confidence": 0.0, "fallbackReason": "no_relevant_local_sources"}
                if action_result and action_result.handled and action_result.llm_prompt:
                    llm_prompt = action_result.llm_prompt
                    citations = action_result.citations
                    rag_trace = {"retrievalMode": "hybrid", "confidence": 0.8, "fallbackReason": None}
                llm_prompt = self._with_conversation(llm_prompt, request)
                llm_result = self._store.ai_runtime.generate_reply(
                    prompt=llm_prompt, language_mode=self._store.intelligence_language_mode,
                    llm_mode="voice",
                )
                if llm_result.get("accepted"):
                    reply = str(llm_result.get("reply") or llm_result.get("response") or "").strip()
                    if not reply:
                        reply = "I heard you, but the model returned an empty response."
                    provider = str(llm_result.get("provider") or "llama.cpp")
                    model = str(llm_result.get("model") or "Qwen/Qwen2.5-7B-Instruct")
                else:
                    reason = str(llm_result.get("reason") or "runtime_unavailable")
                    reply = _LLM_UNAVAILABLE_REPLIES.get(reason, _LLM_FALLBACK_REPLY)
                    provider = str(llm_result.get("provider") or "llama.cpp")
                    model = str(llm_result.get("model") or "fallback")
                    degraded = True
                    fallback_reason = reason
            suggestions = ["Create note", "Add task", "Show status"]
            status = "ready"
            executed_actions = (
                action_result.executed_actions
                if action_result and action_result.handled
                else []
            )
        else:
            reply = "Blocked for safety. Confirm or unlock before risky execution."
            suggestions = ["Explain risk", "Request confirmation", "Open safety panel"]
            status = "blocked"
            provider = "safety_gate"
            model = "policy_only"
            executed_actions = []

        reply = self._style_reply(reply, decision=decision, config=tuning)
        meta = f"{provider or ''}{f' · {model}' if model else ''}".strip(" ·") or None
        self._persist_chat_turn(request, reply, meta=meta)
        return AssistantResponse(
            reply=reply, decision=decision, suggestedActions=suggestions,
            status=status, provider=provider, model=model,
            degraded=degraded, fallbackReason=fallback_reason,
            citations=citations, rag=rag_trace,
            executedActions=executed_actions,
        )

    def _build_llm_prompt_for_request(
        self, request: AssistantRequest
    ) -> tuple[str, dict]:
        tuning = self._store._active_tuning_config()
        decision = self.policy_decision(request, config=tuning)
        citations: list[dict] = []
        rag_trace: dict = {"retrievalMode": "none", "confidence": 0.0, "fallbackReason": None}
        action_result: ActionRouteResult | None = None
        executed_actions: list[ExecutedAction] = []

        if not decision.allowed:
            return "", {
                "allowed": False,
                "decision": decision,
                "rag_trace": rag_trace,
                "citations": citations,
                "executed_actions": executed_actions,
            }

        action_result = self._route_action(request)
        if action_result and action_result.handled and action_result.immediate:
            return "", {
                "allowed": True,
                "decision": decision,
                "immediate_action": action_result,
                "rag_trace": rag_trace,
                "citations": citations,
                "executed_actions": action_result.executed_actions,
            }

        if request.wakeInvoke:
            return self._build_wake_invoke_prompt(), {
                "allowed": True,
                "decision": decision,
                "wake_invoke": True,
                "rag_trace": {"retrievalMode": "none", "confidence": 0.0, "fallbackReason": "wake_invoke"},
                "citations": [],
                "executed_actions": executed_actions,
            }

        latest_snapshot = self._store.memory_db.latest_perception_snapshot()
        lowered = (request.text or "").lower()
        asks_about_screen = any(
            term in lowered
            for term in ("screen", "vision", "display", "what do you see", "what's on screen", "ocr")
        )
        if asks_about_screen and latest_snapshot is not None:
            return "", {
                "allowed": True,
                "decision": decision,
                "screen_snapshot": latest_snapshot,
                "rag_trace": rag_trace,
                "citations": citations,
                "executed_actions": executed_actions,
            }

        rag_items: list[MemoryDocumentChunk] = []
        if not self.is_casual_chat_request(request.text):
            rag_items = self._store.memory_db.search_documents(query=request.text, limit=3)
        if rag_items and self._store._should_attach_document_rag(request.text, rag_items):
            retrieval_mode = self._store._document_retrieval_mode(rag_items)
            confidence = self._store._document_retrieval_confidence(rag_items)
            rag_trace = {"retrievalMode": retrieval_mode, "confidence": confidence, "fallbackReason": None}
            citations = [
                {
                    "chunkId": item.id, "documentId": item.documentId, "sourcePath": item.sourcePath,
                    "title": item.title, "chunkIndex": item.chunkIndex, "score": item.score,
                    "textPreview": item.text[:240],
                }
                for item in rag_items
            ]
            context_blocks = [
                "\n".join([f"Source {i}: {item.title}", f"Path: {item.sourcePath}", f"Excerpt: {item.text[:900]}"])
                for i, item in enumerate(rag_items, start=1)
            ]
            llm_prompt = (
                "Answer using the local source context when it is relevant. "
                "Do not invent citations. If the context is weak, say what is missing.\n\n"
                + "\n\n".join(context_blocks)
                + f"\n\n<user_turn>{request.text}</user_turn>"
            )
        else:
            llm_prompt = f"<user_turn>{request.text}</user_turn>"
            rag_trace = {"retrievalMode": "none", "confidence": 0.0, "fallbackReason": "no_relevant_local_sources"}

        if action_result and action_result.handled and action_result.llm_prompt:
            llm_prompt = action_result.llm_prompt
            citations = action_result.citations
            executed_actions = action_result.executed_actions
            rag_trace = {"retrievalMode": "hybrid", "confidence": 0.8, "fallbackReason": None}

        llm_prompt = self._with_conversation(llm_prompt, request)

        return llm_prompt, {
            "allowed": True,
            "decision": decision,
            "rag_trace": rag_trace,
            "citations": citations,
            "executed_actions": executed_actions,
        }

    def stream_respond(self, request: AssistantRequest):
        import json

        if not self._store.respond_lock.acquire(blocking=False):
            yield f"data: {json.dumps({'error': 'assistant_busy'}, ensure_ascii=True)}\n\n"
            return
        try:
            tuning = self._store._active_tuning_config()
            llm_prompt, meta = self._build_llm_prompt_for_request(request)
            decision = meta["decision"]
            result = "allowed" if decision.allowed else "blocked"
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()), intent=request.text,
                    tier=decision.tier, result=result, reason=decision.reason, createdAt=now_iso(),
                ),
            )

            if not meta.get("allowed", False):
                reply = "Blocked for safety. Confirm or unlock before risky execution."
                yield f"data: {json.dumps({'token': reply}, ensure_ascii=True)}\n\n"
                yield f"data: {json.dumps({'done': True, 'reply': reply, 'status': 'blocked'}, ensure_ascii=True)}\n\n"
                return

            if meta.get("immediate_action") is not None:
                action_result = meta["immediate_action"]
                reply = self._style_reply(action_result.reply, decision=decision, config=tuning)
                self._persist_chat_turn(request, reply, meta="action_router")
                yield f"data: {json.dumps({'token': reply}, ensure_ascii=True)}\n\n"
                yield f"data: {json.dumps({'done': True, 'reply': reply, 'status': 'ready', 'provider': 'action_router', 'model': 'local_rules', 'executedActions': self._serialize_executed_actions(action_result.executed_actions)}, ensure_ascii=True)}\n\n"
                return

            if meta.get("screen_snapshot") is not None:
                latest_snapshot = meta["screen_snapshot"]
                snippet = (latest_snapshot.text or "").strip()
                summary = snippet[:220] if snippet else "No OCR text available."
                reply = (
                    "Latest perception snapshot available. "
                    f"Captured at {latest_snapshot.createdAt}, blocks={latest_snapshot.blockCount}, "
                    f"textLength={latest_snapshot.textLength}. Summary: {summary}"
                )
                reply = self._style_reply(reply, decision=decision, config=tuning)
                yield f"data: {json.dumps({'token': reply}, ensure_ascii=True)}\n\n"
                yield f"data: {json.dumps({'done': True, 'reply': reply, 'status': 'ready', 'provider': 'memory_snapshot', 'model': 'latest_perception_context'}, ensure_ascii=True)}\n\n"
                return

            tokens: list[str] = []
            llm_mode = "voice"
            for event in self._store.ai_runtime.stream_reply_tokens(
                prompt=llm_prompt,
                language_mode=self._store.intelligence_language_mode,
                llm_mode=llm_mode,
            ):
                if event.get("error"):
                    reason = str(event["error"])
                    reply = _LLM_UNAVAILABLE_REPLIES.get(reason, _LLM_FALLBACK_REPLY)
                    yield f"data: {json.dumps({'token': reply}, ensure_ascii=True)}\n\n"
                    yield f"data: {json.dumps({'done': True, 'reply': reply, 'status': 'ready', 'degraded': True, 'fallbackReason': reason}, ensure_ascii=True)}\n\n"
                    return
                token = str(event.get("token", ""))
                if not token:
                    continue
                tokens.append(token)
                yield f"data: {json.dumps({'token': token}, ensure_ascii=True)}\n\n"

            reply = "".join(tokens).strip()
            if meta.get("wake_invoke") and not reply:
                reply = "I am here. What should we tackle first?"
            if not reply:
                reply = "I heard you, but the model returned an empty response."
            reply = self._style_reply(reply, decision=decision, config=tuning)
            self._persist_chat_turn(
                request,
                reply,
                meta=f"llama.server · {self._store.ai_runtime._config.get('voiceModel', 'Qwen/Qwen2.5-3B-Instruct')}",
            )
            suggestions = ["Create note", "Add task", "Show status"] if meta.get("wake_invoke") else ["Create note", "Add task", "Show status"]
            if meta.get("wake_invoke"):
                suggestions = ["Open dashboard", "Review tasks", "Check status"]
            done_payload = {
                "done": True,
                "reply": reply,
                "status": "ready",
                "provider": "llama.server",
                "model": self._store.ai_runtime._config.get("voiceModel", "Qwen/Qwen2.5-3B-Instruct"),
                "suggestedActions": suggestions,
                "citations": meta.get("citations", []),
                "rag": meta.get("rag_trace", {}),
                "executedActions": self._serialize_executed_actions(meta.get("executed_actions", [])),
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=True)}\n\n"
        finally:
            self._store.respond_lock.release()
