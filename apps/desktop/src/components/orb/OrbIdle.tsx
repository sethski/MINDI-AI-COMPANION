import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { debugSessionLog } from "../../lib/debug-session-log";

interface OrbIdleProps {
  offline: boolean;
  wakeListening: boolean;
  micBlocked: boolean;
  nudgeCaption?: string;
  onOpenDashboard: () => void;
  onDragStart: () => void;
  onMenuOpenChange: (open: boolean) => void;
  onQuit: () => void;
}

const DRAG_THRESHOLD_PX = 14;

function setMenuState(
  open: boolean,
  setMenuOpen: (open: boolean) => void,
  onMenuOpenChange: (open: boolean) => void,
) {
  setMenuOpen(open);
  onMenuOpenChange(open);
}

export function OrbIdle({
  offline,
  wakeListening,
  micBlocked,
  nudgeCaption,
  onOpenDashboard,
  onDragStart,
  onMenuOpenChange,
  onQuit,
}: OrbIdleProps) {
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  const dragStartedRef = useRef(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const handleTap = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 || dragStartedRef.current) {
      dragStartedRef.current = false;
      return;
    }
    const start = pointerRef.current;
    pointerRef.current = null;
    if (!start) {
      return;
    }
    const deltaX = Math.abs(event.clientX - start.x);
    const deltaY = Math.abs(event.clientY - start.y);
    if (deltaX > DRAG_THRESHOLD_PX || deltaY > DRAG_THRESHOLD_PX) {
      return;
    }
    const target = event.target as HTMLElement;
    if (target.closest(".orb-idle__menu-item")) {
      return;
    }
    const nextOpen = !menuOpen;
    // #region agent log
    debugSessionLog({
      runId: "post-fix",
      hypothesisId: "H1,H2,H6",
      location: "OrbIdle.tsx:tap",
      message: "orb tap toggles menu",
      data: { menuOpen, nextOpen },
    });
    // #endregion
    setMenuState(nextOpen, setMenuOpen, onMenuOpenChange);
  };

  return (
    <motion.div
      className={`orb-idle ${offline ? "orb-idle--offline" : ""} ${menuOpen ? "orb-idle--menu-open" : ""} ${wakeListening ? "orb-idle--wake" : ""} ${micBlocked ? "orb-idle--mic-blocked" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={
        micBlocked
          ? "MINDI orb. Microphone blocked. Check Windows privacy settings."
          : menuOpen
            ? "MINDI menu open"
            : "MINDI orb. Click for menu. Say Mindi to talk."
      }
      title={
        micBlocked
          ? "Microphone blocked — allow mic for MINDI in Windows Settings"
          : "Click for menu · Say “Mindi” to talk"
      }
      onPointerDown={(event) => {
        if (event.button !== 0) {
          return;
        }
        dragStartedRef.current = false;
        pointerRef.current = { x: event.clientX, y: event.clientY };
      }}
      onPointerMove={(event) => {
        const start = pointerRef.current;
        if (!start || dragStartedRef.current) {
          return;
        }
        const deltaX = Math.abs(event.clientX - start.x);
        const deltaY = Math.abs(event.clientY - start.y);
        if (deltaX > DRAG_THRESHOLD_PX || deltaY > DRAG_THRESHOLD_PX) {
          dragStartedRef.current = true;
          setMenuState(false, setMenuOpen, onMenuOpenChange);
          onDragStart();
        }
      }}
      onPointerUp={handleTap}
      onPointerCancel={() => {
        pointerRef.current = null;
        dragStartedRef.current = false;
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setMenuState(!menuOpen, setMenuOpen, onMenuOpenChange);
        }
        if (event.key === "Escape" && menuOpen) {
          setMenuState(false, setMenuOpen, onMenuOpenChange);
        }
      }}
      whileTap={{ scale: 0.96 }}
      layout
    >
      <div className="orb-idle__core" aria-hidden="true">
        {wakeListening ? <span className="orb-idle__wake-ring" aria-hidden="true" /> : null}
        {micBlocked ? <span className="orb-idle__mic-blocked" aria-hidden="true" /> : null}
      </div>
      {nudgeCaption ? (
        <p className="orb-idle__nudge" role="status">
          {nudgeCaption}
        </p>
      ) : null}
      {menuOpen ? (
        <div className="orb-idle__menu" role="menu">
          <button
            type="button"
            role="menuitem"
            className="orb-idle__menu-item"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              setMenuState(false, setMenuOpen, onMenuOpenChange);
              onOpenDashboard();
            }}
          >
            Open MINDI
          </button>
          <button
            type="button"
            role="menuitem"
            className="orb-idle__menu-item"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              setMenuState(false, setMenuOpen, onMenuOpenChange);
              onQuit();
            }}
          >
            Quit MINDI
          </button>
        </div>
      ) : null}
    </motion.div>
  );
}

type ActivePhase = "waking" | "greeting" | "listening" | "thinking" | "speaking" | "error";

interface OrbActiveProps {
  phase: ActivePhase;
  caption: string;
  offline: boolean;
  reducedMotion: boolean;
  onDragStart: () => void;
  onCancel: () => void;
  waveform: React.ReactNode;
  pulse: React.ReactNode;
}

export function OrbActive({
  phase,
  caption,
  offline,
  reducedMotion,
  onDragStart,
  onCancel,
  waveform,
  pulse,
}: OrbActiveProps) {
  const showCaption = phase === "error";

  return (
    <motion.div
      className={`orb-active ${offline ? "orb-active--offline" : ""} orb-active--${phase}`}
      initial={reducedMotion ? false : { opacity: 0, scale: 0.82 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={reducedMotion ? undefined : { opacity: 0, scale: 0.88 }}
      transition={{ type: "spring", stiffness: 100, damping: 20 }}
      layout
      aria-live="polite"
      aria-label={caption || formatPhase(phase)}
    >
      {!reducedMotion ? pulse : null}
      <div className="orb-active__header">
        <button
          type="button"
          className="orb-active__drag"
          aria-label="Drag MINDI orb"
          onPointerDown={(event) => {
            if (event.button === 0) {
              onDragStart();
            }
          }}
        />
        <span className="orb-active__phase">{formatPhase(phase)}</span>
        <button type="button" className="orb-active__close" onClick={onCancel} aria-label="End call">
          ×
        </button>
      </div>
      <div className="orb-active__body">
        {!reducedMotion ? waveform : <span className="orb-active__static-mark" aria-hidden="true" />}
        {showCaption ? <p className="orb-active__caption">{caption}</p> : null}
      </div>
    </motion.div>
  );
}

function formatPhase(phase: ActivePhase): string {
  switch (phase) {
    case "waking":
      return "Connecting";
    case "greeting":
      return "Ready";
    case "listening":
      return "Listening";
    case "thinking":
      return "Thinking";
    case "speaking":
      return "Speaking";
    case "error":
      return "Error";
    default:
      return "MINDI";
  }
}
