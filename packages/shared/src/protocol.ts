export type MindiTabId =
  | "home"
  | "control"
  | "memory"
  | "vision"
  | "ops"
  | "safety"
  | "settings";

export type ActionTier = "read_only" | "reversible" | "risky" | "destructive";

export interface PolicyDecision {
  allowed: boolean;
  tier: ActionTier;
  reason: string;
  requiresUnlock: boolean;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  timestamp?: string;
}

export interface AssistantRequest {
  text: string;
  mode?: "chat" | "action";
  tab?: MindiTabId;
  conversation?: ChatMessage[];
}

export interface AssistantResponse {
  reply: string;
  decision: PolicyDecision;
  suggestedActions: string[];
  status: string;
}

export interface AgentStatus {
  state: "ready" | "offline" | "busy" | "blocked";
  uptimeSeconds: number;
  activeTask?: string;
  listening: boolean;
  agentVersion: string;
  currentProfile: string;
}

export interface QuickToggle {
  id: string;
  label: string;
  enabled: boolean;
}

export const TAB_ORDER: MindiTabId[] = [
  "home",
  "control",
  "memory",
  "vision",
  "ops",
  "safety",
  "settings",
];

export const QUICK_TOGGLES: QuickToggle[] = [
  { id: "readOnly", label: "Read-only", enabled: true },
  { id: "screen", label: "Screen capture", enabled: false },
  { id: "mic", label: "Mic", enabled: true },
  { id: "webcam", label: "Webcam", enabled: false },
  { id: "automation", label: "Automation", enabled: false },
];

