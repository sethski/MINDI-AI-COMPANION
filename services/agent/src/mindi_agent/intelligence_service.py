"""Intelligence adaptation: style, tuning, learning, eval, and LoRA export."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .dataset_pipeline import prepare_ph_dataset_artifacts
from .schemas import (
    ActionLogItem,
    ActionTier,
    AssistantRequest,
    DatasetPrepareRequest,
    DatasetPrepareResponse,
    IntelligenceAdaptationExportResponse,
    IntelligenceAdaptationStatus,
    IntelligenceEvalCaseResult,
    IntelligenceEvalRunRequest,
    IntelligenceEvalRunResponse,
    IntelligenceLearningApplyRequest,
    IntelligenceLearningApplyResponse,
    IntelligenceLearningCandidate,
    IntelligenceLearningRunResponse,
    IntelligenceLearningSourceRequest,
    IntelligenceLearningSourceResponse,
    IntelligenceLearningSourceSummary,
    IntelligenceLearningStatus,
    IntelligenceStyleStatus,
    IntelligenceStyleUpdateRequest,
    IntelligenceTuningApplyResponse,
    IntelligenceTuningConfig,
    IntelligenceTuningStageRequest,
    IntelligenceTuningStatus,
    now_iso,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

SLANG_EXPLICIT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?im)\b(?:slang|term|phrase)\s*[:=-]\s*([A-Za-z][A-Za-z0-9'-]{1,19})\b"),
    re.compile(r"(?im)\b([A-Za-z][A-Za-z0-9'-]{1,19})\b\s*[-:]\s*(?:slang|taglish|tagalog)\b"),
]

LEARNING_SOURCE_TAGS = {"style", "slang", "taglish", "tagalog", "language"}

LEARNING_BLOCKED_TERMS = {
    "app",
    "browser",
    "brave",
    "chrome",
    "cmd",
    "edge",
    "firefox",
    "notepad",
    "powershell",
    "terminal",
}


# ---------------------------------------------------------------------------
# IntelligenceService
# ---------------------------------------------------------------------------

class IntelligenceService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    # --- Dataset preparation ---

    def prepare_intelligence_dataset(self, request: DatasetPrepareRequest) -> DatasetPrepareResponse:
        dataset_path = Path(request.datasetPath).resolve()
        _missing_response = DatasetPrepareResponse(
            accepted=False,
            reason="dataset_not_found",
            datasetPath=str(dataset_path),
            outputDir=str(Path("data/runtime/intelligence").resolve()),
            rawSamples=0,
            trainSamples=0,
            valSamples=0,
            validationPassed=False,
            validationIssues=["dataset_not_found"],
            languagePackLoaded=False,
            languagePackLoadReason="dataset_not_found",
        )
        if not dataset_path.exists():
            return _missing_response
        if not self._store._is_path_allowed(dataset_path):
            return DatasetPrepareResponse(
                accepted=False,
                reason="dataset_path_not_allowed",
                datasetPath=str(dataset_path),
                outputDir=str(Path("data/runtime/intelligence").resolve()),
                rawSamples=0,
                trainSamples=0,
                valSamples=0,
                validationPassed=False,
                validationIssues=["dataset_path_not_allowed"],
                languagePackLoaded=False,
                languagePackLoadReason="dataset_path_not_allowed",
            )

        output_dir = (
            Path(request.outputDir).resolve() if request.outputDir
            else Path("data/runtime/intelligence").resolve()
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        result = prepare_ph_dataset_artifacts(
            dataset_path=dataset_path,
            output_dir=output_dir,
            max_samples=request.maxSamples,
            languages=request.languages,
            quality_buckets=request.qualityBuckets,
        )
        language_pack_loaded = False
        language_pack_load_reason: str | None = None
        if result.accepted and result.languagePackPath:
            try:
                runtime_status = self._store.ai_runtime.update_config(
                    {"llmLanguagePackPath": result.languagePackPath}
                )
                config_payload = runtime_status.get("config", {})
                configured_path = str(config_payload.get("llmLanguagePackPath", "")).strip()
                language_pack_loaded = configured_path == result.languagePackPath
                language_pack_load_reason = "loaded" if language_pack_loaded else "runtime_config_rejected"
            except Exception:
                language_pack_loaded = False
                language_pack_load_reason = "runtime_config_update_failed"
            if not language_pack_loaded:
                result.accepted = False
                result.reason = "language_pack_load_failed"
                issues = result.validationIssues or []
                result.validationIssues = issues + [language_pack_load_reason or "language_pack_load_failed"]
                result.validationPassed = False
        if result.accepted:
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent="intelligence_dataset_prepare",
                    tier=ActionTier.reversible,
                    result="allowed",
                    reason=f"samples:{result.rawSamples}",
                    createdAt=now_iso(),
                ),
            )
        return DatasetPrepareResponse(
            accepted=result.accepted,
            reason=result.reason,
            datasetPath=result.datasetPath,
            outputDir=result.outputDir,
            rawSamples=result.rawSamples,
            sampleCount=result.rawSamples,
            trainSamples=result.trainSamples,
            valSamples=result.valSamples,
            languagePackPath=result.languagePackPath,
            trainJsonlPath=result.trainJsonlPath,
            valJsonlPath=result.valJsonlPath,
            configPath=result.configPath,
            manifestPath=result.manifestPath,
            validationPassed=result.validationPassed,
            validationIssues=result.validationIssues or [],
            languagePackLoaded=language_pack_loaded,
            languagePackLoadReason=language_pack_load_reason,
        )

    # --- Tuning config helpers ---

    def active_tuning_config(self) -> IntelligenceTuningConfig:
        return IntelligenceTuningConfig(
            preset=self._store.intelligence_tuning_preset,  # type: ignore[arg-type]
            responseVerbosity=self._store.intelligence_tuning_verbosity,  # type: ignore[arg-type]
            customRiskyTerms=self._store.intelligence_tuning_custom_risky_terms[:50],
        )

    def pending_tuning_config(self) -> IntelligenceTuningConfig | None:
        if self._store.intelligence_tuning_pending_version is None:
            return None
        return IntelligenceTuningConfig(
            preset=self._store.intelligence_tuning_pending_preset or self._store.intelligence_tuning_preset,  # type: ignore[arg-type]
            responseVerbosity=self._store.intelligence_tuning_pending_verbosity or self._store.intelligence_tuning_verbosity,  # type: ignore[arg-type]
            customRiskyTerms=self._store.intelligence_tuning_pending_custom_risky_terms[:50],
        )

    @staticmethod
    def normalized_risky_terms(config: IntelligenceTuningConfig) -> set[str]:
        base_terms = {
            "delete",
            "remove",
            "uninstall",
            "registry",
            "firewall",
            "credential",
        }
        return base_terms | {term.strip().lower() for term in config.customRiskyTerms if term.strip()}

    # --- Style ---

    def intelligence_style_status(self) -> IntelligenceStyleStatus:
        return IntelligenceStyleStatus(
            languageMode=self._store.intelligence_language_mode,  # type: ignore[arg-type]
            slangEnabled=self._store.intelligence_slang_enabled,
            slangTerms=self._store.intelligence_slang_terms[:50],
        )

    def update_intelligence_style(
        self, request: IntelligenceStyleUpdateRequest
    ) -> IntelligenceStyleStatus:
        if request.languageMode is not None:
            self._store.intelligence_language_mode = request.languageMode
        if request.slangEnabled is not None:
            self._store.intelligence_slang_enabled = bool(request.slangEnabled)
        if request.resetSlangTerms:
            self._store.intelligence_slang_terms = []
        if request.addSlangTerms:
            normalized = [term.strip() for term in request.addSlangTerms if term.strip()]
            for term in normalized:
                if term.lower() not in {item.lower() for item in self._store.intelligence_slang_terms}:
                    self._store.intelligence_slang_terms.append(term)
            self._store.intelligence_slang_terms = self._store.intelligence_slang_terms[:50]
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_style_update",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"mode:{self._store.intelligence_language_mode},slang:{self._store.intelligence_slang_enabled}",
                createdAt=now_iso(),
            ),
        )
        return self.intelligence_style_status()

    # --- Adaptation status ---

    def _latest_eval_score(self, scope: str) -> float | None:
        for item in self._store.intelligence_eval_history:
            if item.scope == scope:
                return item.score
        return None

    def intelligence_adaptation_status(self) -> IntelligenceAdaptationStatus:
        total_eval_runs = len(self._store.intelligence_eval_history)
        passed_active_runs = sum(
            1 for item in self._store.intelligence_eval_history if item.scope == "active" and item.score >= 1.0
        )
        passed_pending_runs = sum(
            1 for item in self._store.intelligence_eval_history if item.scope == "pending" and item.score >= 1.0
        )
        passed_learning_runs = sum(
            1 for item in self._store.intelligence_eval_history if item.scope == "learning" and item.score >= 1.0
        )
        latest_active_score = self._latest_eval_score("active")
        latest_pending_score = self._latest_eval_score("pending")
        latest_learning_score = self._latest_eval_score("learning")
        approved_source_count = len(self._store.intelligence_learning_sources)
        applied_slang_count = len(self._store.intelligence_slang_terms)
        custom_risky_term_count = len(self._store.intelligence_tuning_custom_risky_terms)
        prompt_stable = bool(
            total_eval_runs >= 2
            and passed_active_runs >= 1
            and passed_pending_runs >= 1
            and latest_active_score is not None
            and latest_active_score >= 1.0
            and latest_pending_score is not None
            and latest_pending_score >= 1.0
        )
        lora_stable = bool(
            prompt_stable
            and total_eval_runs >= 3
            and passed_learning_runs >= 1
            and latest_learning_score is not None
            and latest_learning_score >= 1.0
        )
        if lora_stable and applied_slang_count > 0:
            justified = True
            recommended_method = "lora"
            reason = "lora_ready"
        elif prompt_stable:
            justified = False
            recommended_method = "prompt_only"
            reason = "prompt_controls_sufficient"
        else:
            justified = False
            recommended_method = "none"
            reason = "insufficient_eval_evidence"
        return IntelligenceAdaptationStatus(
            justified=justified,
            recommendedMethod=recommended_method,  # type: ignore[arg-type]
            reason=reason,
            totalEvalRuns=total_eval_runs,
            passedActiveRuns=passed_active_runs,
            passedPendingRuns=passed_pending_runs,
            passedLearningRuns=passed_learning_runs,
            latestActiveScore=latest_active_score,
            latestPendingScore=latest_pending_score,
            latestLearningScore=latest_learning_score,
            approvedSourceCount=approved_source_count,
            appliedSlangCount=applied_slang_count,
            customRiskyTermCount=custom_risky_term_count,
            exportReady=justified and recommended_method == "lora",
            lastExportAt=self._store.intelligence_adaptation_last_export_at,
            lastExportPath=self._store.intelligence_adaptation_last_export_path,
        )

    # --- Tuning ---

    def intelligence_tuning_status(self) -> IntelligenceTuningStatus:
        pending = self.pending_tuning_config()
        can_apply_pending = bool(
            pending is not None
            and self._store.intelligence_tuning_pending_version is not None
            and self._store.intelligence_tuning_last_pending_eval_version == self._store.intelligence_tuning_pending_version
            and self._store.intelligence_tuning_last_pending_eval_score is not None
            and self._store.intelligence_tuning_last_pending_eval_score >= 1.0
        )
        return IntelligenceTuningStatus(
            active=self.active_tuning_config(),
            pending=pending,
            pendingVersion=self._store.intelligence_tuning_pending_version,
            lastActiveEvalScore=self._store.intelligence_tuning_last_active_eval_score,
            lastPendingEvalScore=self._store.intelligence_tuning_last_pending_eval_score,
            lastPendingEvalVersion=self._store.intelligence_tuning_last_pending_eval_version,
            minApplyScore=1.0,
            canApplyPending=can_apply_pending,
        )

    def stage_intelligence_tuning(
        self, request: IntelligenceTuningStageRequest
    ) -> IntelligenceTuningStatus:
        base = self.pending_tuning_config() or self.active_tuning_config()
        preset = request.preset or base.preset
        verbosity = request.responseVerbosity or base.responseVerbosity
        custom_terms = base.customRiskyTerms[:]
        if request.resetCustomRiskyTerms:
            custom_terms = []
        if request.addCustomRiskyTerms:
            for raw_term in request.addCustomRiskyTerms:
                term = raw_term.strip()
                if not term:
                    continue
                if term.lower() not in {item.lower() for item in custom_terms}:
                    custom_terms.append(term)
        self._store.intelligence_tuning_pending_preset = preset
        self._store.intelligence_tuning_pending_verbosity = verbosity
        self._store.intelligence_tuning_pending_custom_risky_terms = custom_terms[:50]
        self._store.intelligence_tuning_pending_version = str(uuid4())
        self._store.intelligence_tuning_last_pending_eval_score = None
        self._store.intelligence_tuning_last_pending_eval_version = None
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_tuning_stage",
                tier=ActionTier.reversible,
                result="allowed",
                reason=(
                    f"preset:{self._store.intelligence_tuning_pending_preset},"
                    f"verbosity:{self._store.intelligence_tuning_pending_verbosity}"
                ),
                createdAt=now_iso(),
            ),
        )
        return self.intelligence_tuning_status()

    def discard_intelligence_tuning(self) -> IntelligenceTuningStatus:
        self._store.intelligence_tuning_pending_preset = None
        self._store.intelligence_tuning_pending_verbosity = None
        self._store.intelligence_tuning_pending_custom_risky_terms = []
        self._store.intelligence_tuning_pending_version = None
        self._store.intelligence_tuning_last_pending_eval_score = None
        self._store.intelligence_tuning_last_pending_eval_version = None
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_tuning_discard",
                tier=ActionTier.reversible,
                result="allowed",
                reason="pending_cleared",
                createdAt=now_iso(),
            ),
        )
        return self.intelligence_tuning_status()

    def apply_intelligence_tuning(self) -> IntelligenceTuningApplyResponse:
        status = self.intelligence_tuning_status()
        if status.pending is None or status.pendingVersion is None:
            return IntelligenceTuningApplyResponse(accepted=False, reason="no_pending_candidate", status=status)
        if status.lastPendingEvalVersion != status.pendingVersion:
            return IntelligenceTuningApplyResponse(accepted=False, reason="pending_candidate_not_evaluated", status=status)
        if not status.canApplyPending:
            return IntelligenceTuningApplyResponse(accepted=False, reason="pending_eval_below_threshold", status=status)
        self._store.intelligence_tuning_preset = status.pending.preset
        self._store.intelligence_tuning_verbosity = status.pending.responseVerbosity
        self._store.intelligence_tuning_custom_risky_terms = status.pending.customRiskyTerms[:50]
        self._store.intelligence_tuning_last_active_eval_score = status.lastPendingEvalScore
        self._store.intelligence_tuning_pending_preset = None
        self._store.intelligence_tuning_pending_verbosity = None
        self._store.intelligence_tuning_pending_custom_risky_terms = []
        self._store.intelligence_tuning_pending_version = None
        self._store.intelligence_tuning_last_pending_eval_score = None
        self._store.intelligence_tuning_last_pending_eval_version = None
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_tuning_apply",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"preset:{self._store.intelligence_tuning_preset},verbosity:{self._store.intelligence_tuning_verbosity}",
                createdAt=now_iso(),
            ),
        )
        return IntelligenceTuningApplyResponse(
            accepted=True, reason="applied", status=self.intelligence_tuning_status()
        )

    # --- Eval ---

    def run_intelligence_eval(
        self, request: IntelligenceEvalRunRequest | None = None
    ) -> IntelligenceEvalRunResponse:
        payload = request or IntelligenceEvalRunRequest()
        scope = payload.scope

        if scope == "learning":
            return self._run_learning_eval(payload)

        if scope == "pending":
            config = self.pending_tuning_config()
            pending_version = self._store.intelligence_tuning_pending_version
            if config is None or pending_version is None:
                return IntelligenceEvalRunResponse(
                    accepted=False,
                    reason="no_pending_candidate",
                    runId=str(uuid4()),
                    createdAt=now_iso(),
                    scope="pending",
                    gatePassed=False,
                    totalCases=0,
                    passedCases=0,
                    score=0.0,
                    candidateVersion=None,
                    evaluatedTerms=[],
                    cases=[],
                )
        else:
            config = self.active_tuning_config()
            pending_version = None

        cases = [
            ("policy_safe", "summarize my notes", True, False),
            ("policy_risky", "delete all files", False, True),
            ("policy_open_app", "open notepad", True, False),
        ]
        results: list[IntelligenceEvalCaseResult] = []
        passed = 0
        for case_id, text, expected_allowed, expected_unlock in cases:
            decision = self._store.policy_decision(AssistantRequest(text=text), config=config)
            actual_allowed = decision.allowed
            actual_unlock = decision.requiresUnlock
            ok = actual_allowed == expected_allowed and actual_unlock == expected_unlock
            if ok:
                passed += 1
            results.append(
                IntelligenceEvalCaseResult(
                    id=case_id,
                    accepted=ok,
                    score=1.0 if ok else 0.0,
                    expected=f"allowed={expected_allowed},unlock={expected_unlock}",
                    observed=f"allowed={actual_allowed},unlock={actual_unlock}",
                )
            )

        total = len(results)
        score = float(passed) / float(total) if total > 0 else 0.0
        gate_passed = scope == "pending" and score >= 1.0
        run = IntelligenceEvalRunResponse(
            accepted=True,
            reason="ok",
            runId=str(uuid4()),
            createdAt=now_iso(),
            scope=scope,
            gatePassed=gate_passed,
            totalCases=total,
            passedCases=passed,
            score=score,
            candidateVersion=None,
            evaluatedTerms=[],
            cases=results,
        )
        if scope == "pending":
            self._store.intelligence_tuning_last_pending_eval_score = score
            self._store.intelligence_tuning_last_pending_eval_version = pending_version
        else:
            self._store.intelligence_tuning_last_active_eval_score = score
        self._store.intelligence_eval_history.insert(0, run)
        self._store.intelligence_eval_history = self._store.intelligence_eval_history[:50]
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_eval_run",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"scope:{scope},score:{score:.2f}",
                createdAt=now_iso(),
            ),
        )
        return run

    def _run_learning_eval(self, payload: IntelligenceEvalRunRequest) -> IntelligenceEvalRunResponse:
        scope = "learning"
        candidate_version = self._store.intelligence_learning_candidate_version
        selected_terms = self._selected_learning_terms(payload.terms)
        if candidate_version is None or not self._store.intelligence_learning_candidates:
            return IntelligenceEvalRunResponse(
                accepted=False,
                reason="no_learning_candidates",
                runId=str(uuid4()),
                createdAt=now_iso(),
                scope=scope,
                gatePassed=False,
                totalCases=0,
                passedCases=0,
                score=0.0,
                candidateVersion=None,
                evaluatedTerms=[],
                cases=[],
            )
        if not selected_terms:
            return IntelligenceEvalRunResponse(
                accepted=False,
                reason="invalid_learning_terms",
                runId=str(uuid4()),
                createdAt=now_iso(),
                scope=scope,
                gatePassed=False,
                totalCases=0,
                passedCases=0,
                score=0.0,
                candidateVersion=candidate_version,
                evaluatedTerms=[],
                cases=[],
            )

        active_config = self.active_tuning_config()
        safe_decision = self._store.policy_decision(AssistantRequest(text="summarize my notes"), config=active_config)
        safe_reply = self._store._style_reply(
            "Acknowledged. I can proceed locally and keep this action in audit logs.",
            decision=safe_decision,
            config=active_config,
            slang_enabled=True,
            slang_terms=selected_terms,
        )
        risky_decision = self._store.policy_decision(AssistantRequest(text="delete all files"), config=active_config)
        learning_cases = [
            (
                "style_learned_slang_reply",
                f"[{selected_terms[0]}]" in safe_reply,
                f"reply contains [{selected_terms[0]}]",
                safe_reply,
            ),
            (
                "style_learned_slang_single_append",
                safe_reply.count("[") == 1 and safe_reply.count("]") == 1,
                "exactly one slang marker appended",
                safe_reply,
            ),
            (
                "policy_learning_risky",
                risky_decision.allowed is False and risky_decision.requiresUnlock is True,
                "allowed=False,unlock=True",
                f"allowed={risky_decision.allowed},unlock={risky_decision.requiresUnlock}",
            ),
        ]
        learning_results: list[IntelligenceEvalCaseResult] = []
        passed = 0
        for case_id, ok, expected, observed in learning_cases:
            if ok:
                passed += 1
            learning_results.append(
                IntelligenceEvalCaseResult(
                    id=case_id,
                    accepted=ok,
                    score=1.0 if ok else 0.0,
                    expected=expected,
                    observed=observed,
                )
            )

        total = len(learning_results)
        score = float(passed) / float(total) if total > 0 else 0.0
        gate_passed = score >= 1.0
        run = IntelligenceEvalRunResponse(
            accepted=True,
            reason="ok",
            runId=str(uuid4()),
            createdAt=now_iso(),
            scope=scope,
            gatePassed=gate_passed,
            totalCases=total,
            passedCases=passed,
            score=score,
            candidateVersion=candidate_version,
            evaluatedTerms=selected_terms,
            cases=learning_results,
        )
        self._store.intelligence_learning_last_eval_score = score
        self._store.intelligence_learning_last_eval_version = candidate_version
        self._store.intelligence_learning_last_eval_signature = _learning_terms_signature(selected_terms)
        self._store.intelligence_eval_history.insert(0, run)
        self._store.intelligence_eval_history = self._store.intelligence_eval_history[:50]
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_eval_run",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"scope:{scope},score:{score:.2f},terms:{len(selected_terms)}",
                createdAt=now_iso(),
            ),
        )
        return run

    def list_intelligence_eval_history(self, limit: int = 20) -> list[IntelligenceEvalRunResponse]:
        return self._store.intelligence_eval_history[: max(1, min(limit, 200))]

    # --- Learning ---

    @staticmethod
    def extract_slang_candidates_from_text(text: str) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for pattern in SLANG_EXPLICIT_PATTERNS:
                for match in pattern.finditer(line):
                    term = (match.group(1) or "").strip().lower()
                    if len(term) < 2 or term in seen:
                        continue
                    seen.add(term)
                    candidates.append((term, line[:180]))
        return candidates

    def _note_is_learning_source_eligible(self, note) -> bool:
        note_tags = {tag.strip().lower() for tag in note.tags if tag.strip()}
        if note_tags & LEARNING_SOURCE_TAGS:
            return True
        return bool(self.extract_slang_candidates_from_text(note.content))

    def _learning_candidate_allowed(self, term: str) -> bool:
        normalized = term.strip().lower()
        if not normalized:
            return False
        if normalized in LEARNING_BLOCKED_TERMS:
            return False
        risky_terms = self.normalized_risky_terms(self.active_tuning_config())
        return normalized not in risky_terms

    def _clear_learning_eval_gate(self) -> None:
        self._store.intelligence_learning_last_eval_score = None
        self._store.intelligence_learning_last_eval_version = None
        self._store.intelligence_learning_last_eval_signature = None

    def _set_learning_candidates(self, candidates: list[IntelligenceLearningCandidate]) -> None:
        self._store.intelligence_learning_candidates = candidates[:50]
        self._store.intelligence_learning_candidate_version = (
            str(uuid4()) if self._store.intelligence_learning_candidates else None
        )
        self._clear_learning_eval_gate()

    def _selected_learning_terms(self, request_terms: list[str]) -> list[str]:
        available_by_term = {
            item.term.lower(): item.term.lower()
            for item in self._store.intelligence_learning_candidates
        }
        if request_terms:
            ordered: list[str] = []
            seen: set[str] = set()
            for raw_term in request_terms:
                term = raw_term.strip().lower()
                if not term or term in seen:
                    continue
                if term not in available_by_term:
                    return []
                seen.add(term)
                ordered.append(term)
            return ordered
        return list(available_by_term.keys())

    def intelligence_learning_status(self) -> IntelligenceLearningStatus:
        approved_sources = sorted(
            self._store.intelligence_learning_sources.values(),
            key=lambda item: item.approvedAt,
            reverse=True,
        )
        current_signature = _learning_terms_signature(
            [item.term for item in self._store.intelligence_learning_candidates]
        )
        can_apply_candidates = bool(
            self._store.intelligence_learning_candidate_version is not None
            and self._store.intelligence_learning_last_eval_version == self._store.intelligence_learning_candidate_version
            and self._store.intelligence_learning_last_eval_score is not None
            and self._store.intelligence_learning_last_eval_score >= 1.0
            and self._store.intelligence_learning_last_eval_signature == current_signature
        )
        return IntelligenceLearningStatus(
            approvedSources=approved_sources,
            candidates=self._store.intelligence_learning_candidates[:50],
            candidateVersion=self._store.intelligence_learning_candidate_version,
            lastRunAt=self._store.intelligence_learning_last_run_at,
            lastEvalScore=self._store.intelligence_learning_last_eval_score,
            lastEvalVersion=self._store.intelligence_learning_last_eval_version,
            lastAppliedAt=self._store.intelligence_learning_last_applied_at,
            minApplyScore=1.0,
            canApplyCandidates=can_apply_candidates,
        )

    def update_intelligence_learning_source(
        self, request: IntelligenceLearningSourceRequest
    ) -> IntelligenceLearningSourceResponse:
        note = self._store.memory_db.get_note(request.noteId)
        if note is None:
            return IntelligenceLearningSourceResponse(
                accepted=False,
                reason="note_not_found",
                status=self.intelligence_learning_status(),
            )
        if request.approved:
            if not self._note_is_learning_source_eligible(note):
                return IntelligenceLearningSourceResponse(
                    accepted=False,
                    reason="note_not_learning_source",
                    status=self.intelligence_learning_status(),
                )
            self._store.intelligence_learning_sources[note.id] = IntelligenceLearningSourceSummary(
                noteId=note.id,
                title=note.title,
                tags=note.tags,
                approvedAt=now_iso(),
            )
            reason = "source_approved"
        else:
            self._store.intelligence_learning_sources.pop(note.id, None)
            remaining_candidates = [
                item for item in self._store.intelligence_learning_candidates if item.sourceNoteId != note.id
            ]
            self._set_learning_candidates(remaining_candidates)
            reason = "source_removed"
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_learning_source_update",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"{reason}:{note.id}",
                createdAt=now_iso(),
            ),
        )
        return IntelligenceLearningSourceResponse(
            accepted=True,
            reason=reason,
            status=self.intelligence_learning_status(),
        )

    def run_intelligence_learning(self) -> IntelligenceLearningRunResponse:
        approved_sources = list(self._store.intelligence_learning_sources.values())
        if not approved_sources:
            return IntelligenceLearningRunResponse(
                accepted=False,
                reason="no_approved_sources",
                scannedSources=0,
                candidateCount=0,
                candidates=[],
                status=self.intelligence_learning_status(),
            )

        existing_terms = {term.lower() for term in self._store.intelligence_slang_terms}
        results: list[IntelligenceLearningCandidate] = []
        seen_pairs: set[tuple[str, str]] = set()
        for source in approved_sources:
            note = self._store.memory_db.get_note(source.noteId)
            if note is None:
                continue
            for term, evidence in self.extract_slang_candidates_from_text(note.content):
                if term in existing_terms:
                    continue
                if not self._learning_candidate_allowed(term):
                    continue
                key = (source.noteId, term)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                results.append(
                    IntelligenceLearningCandidate(
                        term=term,
                        sourceNoteId=source.noteId,
                        sourceTitle=note.title,
                        evidence=evidence,
                    )
                )

        self._set_learning_candidates(results)
        self._store.intelligence_learning_last_run_at = now_iso()
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_learning_run",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"sources:{len(approved_sources)},candidates:{len(self._store.intelligence_learning_candidates)}",
                createdAt=self._store.intelligence_learning_last_run_at,
            ),
        )
        return IntelligenceLearningRunResponse(
            accepted=True,
            reason="ok",
            scannedSources=len(approved_sources),
            candidateCount=len(self._store.intelligence_learning_candidates),
            candidates=self._store.intelligence_learning_candidates[:50],
            status=self.intelligence_learning_status(),
        )

    def apply_intelligence_learning(
        self, request: IntelligenceLearningApplyRequest
    ) -> IntelligenceLearningApplyResponse:
        selected_terms = self._selected_learning_terms(request.terms)
        if not selected_terms:
            return IntelligenceLearningApplyResponse(
                accepted=False,
                reason="no_candidates_selected",
                appliedTerms=[],
                style=self.intelligence_style_status(),
                status=self.intelligence_learning_status(),
            )
        if self._store.intelligence_learning_candidate_version is None:
            return IntelligenceLearningApplyResponse(
                accepted=False,
                reason="learning_candidates_not_evaluated",
                appliedTerms=[],
                style=self.intelligence_style_status(),
                status=self.intelligence_learning_status(),
            )
        selected_signature = _learning_terms_signature(selected_terms)
        if (
            self._store.intelligence_learning_last_eval_version != self._store.intelligence_learning_candidate_version
            or self._store.intelligence_learning_last_eval_signature != selected_signature
        ):
            return IntelligenceLearningApplyResponse(
                accepted=False,
                reason="learning_candidates_not_evaluated",
                appliedTerms=[],
                style=self.intelligence_style_status(),
                status=self.intelligence_learning_status(),
            )
        if (
            self._store.intelligence_learning_last_eval_score is None
            or self._store.intelligence_learning_last_eval_score < 1.0
        ):
            return IntelligenceLearningApplyResponse(
                accepted=False,
                reason="learning_eval_below_threshold",
                appliedTerms=[],
                style=self.intelligence_style_status(),
                status=self.intelligence_learning_status(),
            )

        applied_terms: list[str] = []
        remaining: list[IntelligenceLearningCandidate] = []
        existing_terms = {term.lower() for term in self._store.intelligence_slang_terms}
        selected_term_set = set(selected_terms)
        for item in self._store.intelligence_learning_candidates:
            if item.term.lower() not in selected_term_set:
                remaining.append(item)
                continue
            if item.term.lower() not in existing_terms:
                self._store.intelligence_slang_terms.append(item.term)
                existing_terms.add(item.term.lower())
                applied_terms.append(item.term)
        self._store.intelligence_slang_terms = self._store.intelligence_slang_terms[:50]
        self._set_learning_candidates(remaining)
        if applied_terms and request.enableSlang:
            self._store.intelligence_slang_enabled = True
        self._store.intelligence_learning_last_applied_at = now_iso()
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_learning_apply",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"applied:{len(applied_terms)}",
                createdAt=self._store.intelligence_learning_last_applied_at,
            ),
        )
        return IntelligenceLearningApplyResponse(
            accepted=bool(applied_terms),
            reason="applied" if applied_terms else "terms_already_known",
            appliedTerms=applied_terms,
            style=self.intelligence_style_status(),
            status=self.intelligence_learning_status(),
        )

    # --- Export ---

    def export_intelligence_adaptation(self) -> IntelligenceAdaptationExportResponse:
        status = self.intelligence_adaptation_status()
        if not status.justified or not status.exportReady or status.recommendedMethod != "lora":
            return IntelligenceAdaptationExportResponse(
                accepted=False,
                reason="adaptation_not_justified",
                method=status.recommendedMethod,
                exportPath=None,
                exampleCount=0,
                status=status,
            )

        active_tuning = self.active_tuning_config()
        active_style = self.intelligence_style_status()
        prompts = [
            "summarize my notes",
            "what's on screen right now",
            "delete all files",
        ]
        examples: list[dict[str, object]] = []
        for prompt in prompts:
            decision = self._store.policy_decision(AssistantRequest(text=prompt), config=active_tuning)
            base_reply = (
                "Acknowledged. I can proceed locally and keep this action in audit logs."
                if decision.allowed
                else "Blocked for safety. Confirm or unlock before risky execution."
            )
            examples.append(
                {
                    "input": prompt,
                    "targetReply": self._store._style_reply(base_reply, decision=decision, config=active_tuning),
                    "policy": {
                        "allowed": decision.allowed,
                        "requiresUnlock": decision.requiresUnlock,
                        "tier": decision.tier,
                    },
                }
            )

        export_dir = Path("data/runtime/exports").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        export_name = f"mindi-intelligence-lora-pack-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        export_path = export_dir / export_name
        payload = {
            "createdAt": now_iso(),
            "recommendedMethod": status.recommendedMethod,
            "reason": status.reason,
            "activeStyle": active_style.model_dump(),
            "activeTuning": active_tuning.model_dump(),
            "appliedSlangTerms": self._store.intelligence_slang_terms[:50],
            "approvedLearningSources": [item.model_dump() for item in self._store.intelligence_learning_sources.values()],
            "evalHistory": [item.model_dump() for item in self._store.intelligence_eval_history[:20]],
            "status": status.model_dump(),
            "examples": examples,
        }
        export_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        self._store.intelligence_adaptation_last_export_at = now_iso()
        self._store.intelligence_adaptation_last_export_path = str(export_path)
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="intelligence_adaptation_export",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"method:{status.recommendedMethod},examples:{len(examples)}",
                createdAt=self._store.intelligence_adaptation_last_export_at,
            ),
        )
        return IntelligenceAdaptationExportResponse(
            accepted=True,
            reason="exported",
            method=status.recommendedMethod,
            exportPath=str(export_path),
            exampleCount=len(examples),
            status=self.intelligence_adaptation_status(),
        )


# ---------------------------------------------------------------------------
# Module-level pure helpers (used inside the service)
# ---------------------------------------------------------------------------

def _learning_terms_signature(terms: list[str]) -> str:
    normalized = sorted({term.strip().lower() for term in terms if term.strip()})
    return "|".join(normalized)
