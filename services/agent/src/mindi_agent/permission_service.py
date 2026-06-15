"""Permission grants, action allowlist, and privacy controls."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .privacy_utils import SENSITIVE_TEXT_PATTERNS
from .schemas import (
    ActionLogItem,
    ActionTier,
    AddPermissionGrantRequest,
    PerceptionPermissionStatus,
    PermissionGrant,
    PrivacyStatus,
    PrivacyUpdateRequest,
    now_iso,
)

PERCEPTION_SCREEN_SUBJECT = "perception.screen.capture"
PERCEPTION_CAMERA_SUBJECT = "perception.camera.capture"


class PermissionService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    # --- Path permissions ---

    def is_path_allowed(self, path: Path) -> bool:
        normalized = path.resolve()
        grants = [g for g in self._store.permission_grants if g.scope == "folder"]
        denies = [Path(g.subject).resolve() for g in grants if g.decision == "deny"]
        allows = [Path(g.subject).resolve() for g in grants if g.decision == "allow"]
        if any(str(normalized).startswith(str(deny)) for deny in denies):
            return False
        if not allows:
            return False
        return any(str(normalized).startswith(str(allow)) for allow in allows)

    # --- Action permissions ---

    @staticmethod
    def subject_matches(grant_subject: str, target_subject: str) -> bool:
        grant_value = grant_subject.strip().lower()
        target_value = target_subject.strip().lower()
        if not grant_value:
            return False
        if grant_value == "*" or grant_value == target_value:
            return True
        if grant_value.endswith("*"):
            return target_value.startswith(grant_value[:-1])
        return False

    def resolve_action_permission(self, subject: str) -> str:
        normalized = subject.strip().lower()
        if not normalized:
            return "deny"
        for grant in self._store.permission_grants:
            if grant.scope != "action":
                continue
            if self.subject_matches(grant.subject, normalized):
                return grant.decision
        return "unset"

    def is_action_allowed(self, subject: str) -> bool:
        return self.resolve_action_permission(subject) == "allow"

    # --- Grant management ---

    def list_permissions(self) -> list[PermissionGrant]:
        return self._store.permission_grants

    def add_permission(self, request: AddPermissionGrantRequest) -> PermissionGrant:
        grant = PermissionGrant(
            id=str(uuid4()),
            scope=request.scope,
            subject=request.subject,
            decision=request.decision,
            createdAt=now_iso(),
        )
        self._store.permission_grants.insert(0, grant)
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"permission_grant:{grant.scope}:{grant.subject}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"decision:{grant.decision}",
                createdAt=now_iso(),
            ),
        )
        self._store._persist_durable_state()
        return grant

    # --- Perception permissions ---

    def perception_permission_status(self) -> PerceptionPermissionStatus:
        screen_decision = self.resolve_action_permission(PERCEPTION_SCREEN_SUBJECT)
        camera_decision = self.resolve_action_permission(PERCEPTION_CAMERA_SUBJECT)
        return PerceptionPermissionStatus(
            screenSubject=PERCEPTION_SCREEN_SUBJECT,
            cameraSubject=PERCEPTION_CAMERA_SUBJECT,
            screenAllowed=screen_decision == "allow",
            cameraAllowed=camera_decision == "allow",
            screenDecision=screen_decision,
            cameraDecision=camera_decision,
        )

    # --- Privacy ---

    def privacy_status(self) -> PrivacyStatus:
        return PrivacyStatus(
            redactionEnabled=self._store.privacy_redaction_enabled,
            safeStorageDefault=True,
            sensitivePatternCount=len(SENSITIVE_TEXT_PATTERNS),
        )

    def update_privacy(self, request: PrivacyUpdateRequest) -> PrivacyStatus:
        self._store.privacy_redaction_enabled = bool(request.redactionEnabled)
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="privacy_update",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"redaction:{self._store.privacy_redaction_enabled}",
                createdAt=now_iso(),
            ),
        )
        return self.privacy_status()
