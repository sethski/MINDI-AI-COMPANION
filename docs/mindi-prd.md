# MINDI Product Requirements Document

## 1. Summary
MINDI is a local-first Windows assistant that lives in a notch UI, uses `MINDI` as both wake word and brand, and ships as one product with all core features in the release. The product should feel like a useful assistant first, a control center second, and a private personal memory system third.

This PRD describes the full vision, but the build plan is split into 6 phases so implementation stays controlled and reviewable.

## 1.1 Product Goal
MINDI should behave like a private desktop companion that can listen, talk, understand what is on screen, help with documents and files, manage tasks, and act on the Windows machine safely. It should reduce friction in daily work without sending personal data to cloud services by default.

## 2. Product Definition

### 2.1 Target User
- Primary user: one Windows user with strong privacy expectations.
- Context: mid-range local PC, offline-first usage, personal workflow, and heavy use of notes, files, screen context, and system control.
- Priorities: reliability, safety, speed, and local ownership of data.

### 2.2 Product Identity
- Name: MINDI.
- Wake word: `MINDI`.
- Brand role: the assistant speaks, listens, and presents itself as MINDI everywhere in UI and voice.
- Surface: a notch-style overlay on Windows, with a compact home view and expandable settings panels.

### 2.3 Core Jobs
MINDI must support these core jobs in the release:
- Voice and text chat.
- Windows app control, opening, closing, switching, and organizing.
- File organization and safe cleanup.
- RAG over documents, images, and personal files.
- Note taking and web scraping.
- Screen context awareness and UI assistance.
- Real-time system monitoring.
- Security and threat monitoring.
- Calendar and task management.
- Personal knowledge graph.
- Automation for repeat workflows.

### 2.4 What MINDI Is Not
- Not a generic chatbot page.
- Not a cloud-only assistant.
- Not a desktop toy with only quick replies.
- Not a raw shell wrapper.
- Not a surveillance tool.
- Not a model training experiment first.

## 3. Release Scope

### 3.1 Release Rule
The release should include all core features. Advanced features may ship in limited form or behind toggles if needed, but the product should feel complete on day one.

### 3.2 V1 Feature Boundary
In release, MINDI should cover:
- assistant chat
- notch UI
- quick toggles and settings
- system and security monitoring
- app and file control
- local memory and search
- document and image RAG
- task and calendar support
- note taking
- automation basics

### 3.3 Detailed Feature Matrix

#### A. Conversation
- Supports voice and text.
- Knows when to answer directly and when to ask follow-up questions.
- Can answer in English, Tagalog, Taglish, and user-style slang when enabled.
- Can summarize previous context from memory when relevant.

#### B. PC Control
- Can open, focus, close, and switch apps.
- Can organize files into folders based on user intent or preset rules.
- Can perform reversible changes automatically when allowed.
- Must preview dangerous bulk actions before execution.

#### C. Memory and RAG
- Can index local documents, PDFs, images, screenshots, and notes.
- Can search by semantic meaning, not only filename.
- Can cite the source file or image region used for an answer.
- Can store short-term context, long-term facts, and episodic traces separately.

#### D. Screen Context
- Can read screen text through OCR.
- Can detect UI elements to support actions like click, copy, or explain.
- Can use screen context only when screen capture is enabled.
- Must not log sensitive screen content unless explicitly saved.

#### E. Notes and Knowledge
- Can capture notes from conversations, web pages, and manual input.
- Can link notes into a personal knowledge graph.
- Can retrieve related notes by people, topics, tasks, or projects.

#### F. System and Security
- Can show CPU, RAM, disk, startup impact, and basic health alerts.
- Can flag suspicious processes or abnormal activity.
- Can suggest safe cleanup or optimization steps.
- Cannot make security-sensitive changes silently.

#### G. Automation
- Can trigger multi-step workflows from natural language.
- Can chain tasks like “download, rename, sort, and note this.”
- Must expose each step in logs.
- Must allow user interruption or abort.

#### H. Web Scraping
- Can collect data from allowed sites.
- Can summarize and store useful results locally.
- Must treat page content as untrusted.
- Must not submit credentials or bypass paywalls or protections.

#### I. Calendar and Tasks
- Can create, edit, and remind.
- Can understand time phrases and recurring tasks.
- Can show urgent items first in the hub.
- Must resolve ambiguous date/time with confirmation.

#### J. Slang and Tone
- Can speak in Taglish and user-specific style.
- Can learn new slang words from approved sources.
- Slang is a style layer, not the core reasoning layer.

### 3.4 Settings and Toggles
The notch should expose settings as grouped toggles and panels, not as a long flat list.

#### Home
- Show tasks and alerts first.
- Show conversation second.
- Show status and health third.
- Surface listening state, offline state, and action state.

#### Control
- Enable app control.
- Enable file organization.
- Enable safe cleanup suggestions.
- Enable clipboard assistance.

#### Memory
- Enable document RAG.
- Enable image RAG.
- Enable screenshot memory.
- Enable clipboard memory.
- Enable note capture.
- Enable knowledge graph links.

#### Vision
- Enable screen OCR.
- Enable UI element detection.
- Enable webcam access.
- Enable face detection.
- Enable hand gesture control.

#### Ops
- Enable web scraping.
- Enable system monitoring.
- Enable security alerts.
- Enable automation chains.

#### Safety
- Enable read-only mode.
- Require confirmation for risky actions.
- Require unlock for destructive actions.
- Show audit log.
- Pause assistant.
- Kill switch.

#### Settings
- Voice selection.
- Language mode.
- Hotkey configuration.
- Allowed folders.
- Allowed apps.
- Allowed domains.
- Memory retention rules.
- Privacy mode.

## 4. Notch UX

### 4.1 Home Screen Order
The notch home should be a combined hub, not separate screens.
- First: tasks and alerts.
- Second: conversation.
- Third: status and system health.

### 4.2 UX Principles
- Compact by default, expanded on demand.
- Hybrid behavior, ambient when idle, dense when active.
- Functional top-level tabs with themed subpanels.
- Quick toggles visible at the top.
- Search always available.
- Risky and destructive actions must not live in the same visual area as casual toggles.

### 4.3 Visual Direction
- Style: polished dark.
- Tone: quiet, premium, utility-first, not noisy.
- UI goal: feel intentional, not like a settings dump.

### 4.4 Layout Rules
- Top strip: listening, offline, acting, blocked.
- Main area: urgent items and recent tasks.
- Middle area: chat input and recent conversation.
- Lower area or side rail: status, memory, and quick actions.
- Advanced panels should slide or expand in place, not open cluttered modal windows unless the task absolutely needs interruption.

### 4.5 UX States
- Idle: calm and minimal.
- Listening: visually obvious.
- Thinking: show active processing.
- Acting: show current step and target.
- Blocked: explain why the action was stopped.
- Offline: explain what still works locally.
- Error: show recovery action, not just a failure message.

## 5. Trust Model

### 5.1 Action Tiers
- Safe or read-only actions may run automatically.
- Reversible actions may run automatically if they are inside policy.
- Risky actions require confirmation or explicit trust mode.
- Destructive or security-sensitive actions require unlock.

### 5.2 Default Rules
- External content is untrusted by default.
- Every action must be logged.
- A kill switch, pause mode, and read-only mode must always exist.
- No raw unrestricted shell access by default.

### 5.3 Recovery Rules
- Failed actions should prefer rollback, undo, recycle bin, or safe fallback.
- Sensitive changes should be auditable and explainable.
- If confidence is low, MINDI should ask or show a draft rather than acting blindly.

### 5.4 Detailed Trust Categories

#### Allowed Automatically
- Read documents.
- Search local memory.
- Summarize files and screenshots.
- Open whitelisted apps.
- Create drafts, notes, reminders, and task suggestions.

#### Allowed With Policy
- Move files inside approved folders.
- Rename files according to user rules.
- Create calendar entries in supported formats.
- Trigger approved automations.

#### Requires Confirmation
- Delete files.
- Uninstall apps.
- Bulk move large folders.
- Change startup apps.
- Send messages or emails.
- Access webcam or microphone if not already enabled for the session.

#### Requires Unlock
- Registry edits.
- Firewall or network changes.
- Credential access.
- Security tool changes.
- System service changes.
- Any destructive operation that cannot be safely rolled back.

### 5.5 Prompt Injection Rules
- Web pages, PDFs, screenshots, and OCR text are content, not instructions.
- External content cannot override policy.
- MINDI should quote suspicious instructions instead of obeying them.
- Untrusted instructions must not trigger tool calls directly.

## 6. Technology Assumptions

### 6.1 Stack Direction
The product assumes a Windows-first hybrid stack:
- Desktop UI plus local agent service.
- Local model runtime for the assistant brain.
- Local storage for memory, logs, and embeddings.
- Windows automation layer for PC control.

### 6.2 Suggested Implementation Stack
- UI: Tauri or Electron.
- Agent: Python.
- API bridge: FastAPI.
- Model: Qwen 2.5 local.
- Memory: SQLite plus a vector store.
- Automation: PowerShell, Windows UI Automation, and Playwright.
- Speech: Whisper for STT and Piper for TTS.
- Vision: OpenCV, OCR, and MediaPipe.

### 6.3 Storage and Data Model
- `SQLite` for tasks, settings, logs, and metadata.
- Vector store for semantic memory and retrieval.
- Local filesystem for indexed documents, screenshots, and exports.
- Append-only audit log for action history.
- Separate storage classes for short-term context, long-term memory, and user-approved saved artifacts.

### 6.4 External Integrations
- Windows shell and file system.
- Windows UI Automation.
- Browser automation for web tasks.
- Local microphone and speaker.
- Optional webcam.
- Optional calendar provider if user connects one.

## 7. Six Phases
The 6 phases are both build order and release checkpoints.

### Phase 1, Spine
- Notch shell.
- Wake word and hotkey entry.
- Voice and text chat.
- Basic settings surface.
- Audit log foundation.
- Phase 1 acceptance: MINDI can wake, speak, show the hub, and log every action.

### Phase 2, Control
- App open, close, and switch.
- File organization.
- Safe cleanup.
- Task and calendar basics.
- Basic automation.
- Allowlist and denylist support.
- Phase 2 acceptance: MINDI can safely handle common PC tasks without raw shell exposure.

### Phase 3, Memory
- Document and image RAG.
- Screenshot and OCR memory.
- Clipboard memory.
- Note taking.
- Personal knowledge graph.
- Phase 3 acceptance: MINDI can search and recall local knowledge from documents, images, notes, and screenshots.

### Phase 4, Perception
- Screen context awareness.
- UI element detection.
- Webcam object detection.
- Face detection.
- Hand gesture detection.
- Phase 4 acceptance: MINDI can interpret live visual context well enough to assist with screen and camera-driven tasks.

### Phase 5, Ops
- Web scraping.
- Security and threat monitoring.
- Deeper automation chains.
- Alerts and recovery flows.
- Offline privacy hardening.
- Phase 5 acceptance: MINDI can operate as a reliable local ops assistant with useful monitoring and web research behavior.

### Phase 6, Intelligence
- Self-improvement loop.
- Prompt and policy tuning.
- Style learning for Taglish and slang.
- Light fine-tuning or LoRA, if justified.
- Evaluation suite and reliability tuning.
- Phase 6 acceptance: MINDI behavior is stable enough to justify tuning, with a measurable eval loop and controlled updates.

## 8. Non-Goals
- No cloud-first brain.
- No training the base model from scratch.
- No raw unlimited shell exposure.
- No invisible recording.
- No live self-modifying code in runtime.
- No unsafe auto-install, auto-uninstall, or security changes without unlock.
- No silent background recording or hidden surveillance mode.
- No feature that bypasses user consent for sensitive inputs.

## 8.1 Out of Scope for Release
- Cross-platform desktop support.
- Mobile companion app.
- Public multi-user sharing system.
- SaaS-style hosted backend.
- Plugin marketplace.
- Voice cloning of other people.
- Full autonomous purchase or payment flows.

## 9. Success Metrics
- MINDI wakes reliably by voice or hotkey.
- Home screen loads cleanly and shows tasks, conversation, and status in the right order.
- Core actions can be completed locally.
- Safety rules block destructive or sensitive actions without unlock.
- Logs clearly show what MINDI did and why.
- The product feels fast, private, and dependable in daily use.

### 9.1 Quality Metrics
- Low action failure rate on common workflows.
- Low false-positive block rate for safe actions.
- Fast perceived wake-to-response time.
- High retrieval usefulness for local docs and images.
- Stable behavior across repeated sessions.
- Few user interruptions for routine tasks.

## 10. Primary User Flows

### 10.1 Wake and Ask
1. User says `MINDI` or uses hotkey.
2. Notch opens in listening or ready state.
3. User gives a request by voice or text.
4. MINDI classifies the task, checks policy, and answers or acts.

### 10.2 Safe Action
1. User asks for a reversible task.
2. MINDI checks allowlist and policy.
3. MINDI performs the action.
4. MINDI logs result and shows completion.

### 10.3 Risky Action
1. User asks for a risky task.
2. MINDI explains the impact.
3. User confirms.
4. MINDI executes and logs each step.

### 10.4 Blocked Action
1. User asks for a sensitive or destructive task.
2. MINDI blocks or requests unlock.
3. MINDI explains why.
4. MINDI offers a safe alternative.

### 10.5 Recall and Search
1. User asks about a document, image, or previous note.
2. MINDI searches local memory.
3. MINDI returns a concise answer with source references.

## 11. Onboarding
- Introduce the wake word and hotkey.
- Explain what MINDI can do locally.
- Show privacy and safety defaults.
- Ask for allowed folders, apps, and optional domains.
- Ask whether microphone, webcam, and screen capture are enabled.
- Start in safe mode until the user chooses higher trust.

## 12. Detailed Edge Cases
- Ambiguous dates and times require confirmation.
- Multiple matching files should surface disambiguation.
- Low-confidence OCR or screen detection should ask for retry rather than guessing.
- If a tool fails, MINDI should report the failure and next safe step.
- If the assistant is offline, local functions should still work and cloud-dependent paths should stay disabled.
- If a request conflicts with policy, MINDI should refuse and explain briefly.

## 13. Operating Model
- Settings should be grouped by capability, not by internal subsystem.
- Changes to permissions should be visible and reversible where possible.
- User should be able to inspect logs and memory.
- Persistent permissions should be explicit, not assumed.
- The assistant should prefer reversible workflows over destructive shortcuts.

## 14. Assumptions
- Mid-range Windows PC is the first target.
- Local-first and offline-first are default.
- Heavy model training is not the starting strategy.
- The release should include all core features, but advanced features may be limited or toggle-gated if needed.

## 15. Exact Notch Panel Layouts

### 15.1 Global Shell
- Top bar: MINDI identity, listening state, offline state, action state, and close/minimize controls.
- Search row: global command search and natural language input.
- Main canvas: current hub content for the active tab.
- Bottom strip: quick toggles, hotkey hint, and trust status.

### 15.2 Home Panel
- Section 1: urgent tasks and alerts.
- Section 2: latest conversation turns.
- Section 3: system and safety status.
- Section 4: recent memory hits and recent actions.
- Primary CTA: ask MINDI or trigger a task.

### 15.3 Control Panel
- App actions: open, focus, close, switch.
- File actions: sort, rename, move, archive, preview.
- Cleanup actions: safe cleanup suggestions, junk review, large file review.
- Clipboard actions: copy helper, quick paste history, clipboard search.

### 15.4 Memory Panel
- Search bar for local memory.
- Tabs for documents, images, screenshots, notes, and conversations.
- Result cards with source, time, and confidence.
- Save toggle for user-approved memory items.

### 15.5 Vision Panel
- Screen capture status.
- OCR preview.
- UI element detection status.
- Webcam controls.
- Face and gesture toggles.

### 15.6 Ops Panel
- System health summary.
- Security alerts.
- Web scrape jobs.
- Automation queue.
- Recovery and retry actions.

### 15.7 Safety Panel
- Read-only mode.
- Confirm-risky mode.
- Unlock-required actions.
- Allowlist / denylist editor.
- Audit log viewer.
- Kill switch and pause controls.

### 15.8 Settings Panel
- Voice selection.
- Language and style mode.
- Hotkey assignment.
- Privacy mode.
- Storage retention.
- Allowed folders, apps, and domains.

### 15.9 Interaction Rules
- No modal-first settings flow unless action is inherently blocking.
- Every panel must show current state, available actions, and trust level.
- Dangerous actions must use explicit confirmation language.
- Every action result must be visible without leaving the notch when possible.

## 16. Memory and Data Model

### 16.1 Core Entities
- `UserProfile`: user preferences, language mode, style settings, and trust defaults.
- `Setting`: toggle or configuration entry with value, scope, and last updated time.
- `PermissionGrant`: allowlist or denylist rule for folder, app, domain, device, or action type.
- `ConversationTurn`: one user input or assistant response with timestamp and source.
- `ActionLog`: one assistant action, including intent, policy result, tool calls, and outcome.
- `MemoryItem`: durable memory fact, note, or user-approved trace.
- `Document`: a local file or importable artifact.
- `DocumentChunk`: indexed segment of a document or OCR result.
- `ImageArtifact`: image, screenshot, or frame with metadata.
- `TaskItem`: task, reminder, or calendar-linked item.
- `Automation`: saved workflow definition.
- `SecurityEvent`: monitoring event or alert.

### 16.2 Memory Classes
- Short-term context: temporary session state, recent turns, active task context.
- Long-term memory: stable user preferences, important facts, durable notes.
- Episodic memory: time-bound traces of tasks, actions, or sessions.
- Artifact memory: user-approved documents, screenshots, images, and imported files.

### 16.3 Retention Rules
- Short-term context expires aggressively.
- Long-term memory requires usefulness or explicit approval.
- Sensitive artifacts should not be retained by default unless the user saves them.
- Memory items must keep source, time, and confidence metadata.

### 16.4 Audit Data
- Every tool call should emit an audit event.
- Every permission decision should be logged.
- Every refusal should include a reason code.
- Every rollback or recovery attempt should be traceable.

### 16.5 Data Safety
- Sensitive data must stay local by default.
- Secrets, tokens, and passwords must not be stored in normal memory.
- Indexed content must preserve source boundaries.
- User can inspect and delete stored memory where applicable.

## 17. Test Matrix

### 17.1 Smoke Tests
- App launches successfully.
- Notch opens and closes.
- Wake word triggers MINDI.
- Hotkey triggers MINDI.
- Text input works.
- Voice input works.

### 17.2 Functional Tests
- Open and close an app.
- Move and rename a file.
- Search a local document.
- Search an image or screenshot.
- Create a note.
- Create a task.
- Create a calendar reminder.
- Show system status.
- Return a source-backed answer from memory.

### 17.3 Safety Tests
- Delete action requires unlock.
- Registry action requires unlock.
- Web content cannot override policy.
- Unsafe prompt injection is blocked.
- Unknown file move path is rejected or confirmed.
- Webcam and microphone remain off unless enabled.
- Kill switch immediately pauses actions.

### 17.4 Offline Tests
- Local chat works offline.
- Local memory search works offline.
- Local notes and tasks still work offline.
- Cloud-dependent paths remain disabled or clearly unavailable.

### 17.5 Recovery Tests
- Failed automation reports step and failure point.
- OCR uncertainty asks for retry.
- Conflicting files trigger disambiguation.
- Low-confidence date/time asks for confirmation.
- Action rollback or safe fallback is attempted when possible.

### 17.6 Performance Checks
- Wake-to-ready feels fast.
- Common actions complete without noticeable lag.
- Memory search returns useful results quickly.
- Notch remains responsive while background monitoring runs.
- Large imports do not freeze the UI.

### 17.7 Release Acceptance
- All core jobs are represented in the release.
- Trust model blocks unsafe behavior as specified.
- Notch UX matches the home order and panel structure.
- Memory and search are usable on local files.
- The product feels coherent, not like disconnected feature flags.
