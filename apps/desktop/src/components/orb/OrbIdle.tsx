import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
interface OrbIdleProps {
  offline: boolean;
  micDisabled: boolean;
  onActivate: () => void;
  onOpenDashboard: () => void;
  onDragStart: () => void;
  onMenuOpenChange: (open: boolean) => void;
  onQuit: () => void;
}

const DRAG_THRESHOLD_PX = 6;

function MicGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
      <path
        d="M12 3.5a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0v-5a3 3 0 0 0-3-3Z"
        fill="currentColor"
      />
      <path
        d="M6 11a6 6 0 0 0 12 0M12 17v3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function OrbIdle({
  offline,
  micDisabled,
  onActivate,
  onOpenDashboard,
  onDragStart,
  onMenuOpenChange,
  onQuit,
}: OrbIdleProps) {
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  const draggedRef = useRef(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    onMenuOpenChange(menuOpen);
  }, [menuOpen, onMenuOpenChange]);

  return (
    <motion.div
      className={`orb-idle ${offline ? "orb-idle--offline" : ""} ${menuOpen ? "orb-idle--menu-open" : ""}`}
      onPointerDown={(event) => {
        if (event.button !== 0) {
          return;
        }
        draggedRef.current = false;
        pointerRef.current = { x: event.clientX, y: event.clientY };
      }}
      onPointerMove={(event) => {
        const start = pointerRef.current;
        if (!start || draggedRef.current) {
          return;
        }
        const deltaX = Math.abs(event.clientX - start.x);
        const deltaY = Math.abs(event.clientY - start.y);
        if (deltaX > DRAG_THRESHOLD_PX || deltaY > DRAG_THRESHOLD_PX) {
          draggedRef.current = true;
          setMenuOpen(false);
          onDragStart();
        }
      }}
      onPointerUp={() => {
        pointerRef.current = null;
      }}
      onPointerCancel={() => {
        pointerRef.current = null;
        draggedRef.current = false;
      }}
      onContextMenu={(event) => {
        event.preventDefault();
        setMenuOpen(true);
      }}
      whileTap={{ scale: 0.96 }}
      layout
    >
      <button
        type="button"
        className="orb-idle__core"
        aria-label="Open MINDI menu"
        title="Click to open MINDI menu. Say Hey MINDI or use the mic to talk."
        onClick={() => {
          if (menuOpen) {
            setMenuOpen(false);
            return;
          }
          if (draggedRef.current) {
            return;
          }
          setMenuOpen(true);
        }}
      />
      {menuOpen ? (
        <div className="orb-idle__menu" role="menu">
          <button
            type="button"
            role="menuitem"
            className="orb-idle__menu-item"
            onClick={(event) => {
              event.stopPropagation();
              setMenuOpen(false);
              onOpenDashboard();
            }}
          >
            Open MINDI
          </button>
          <button
            type="button"
            role="menuitem"
            className="orb-idle__menu-item"
            onClick={(event) => {
              event.stopPropagation();
              setMenuOpen(false);
              onQuit();
            }}
          >
            Quit MINDI
          </button>
        </div>
      ) : null}
      <button
        type="button"
        className={`orb-idle__mic ${micDisabled ? "orb-idle__mic--muted" : "orb-idle__mic--ready"}`}
        aria-label={micDisabled ? "Microphone off" : "Start voice with MINDI"}
        title={micDisabled ? "Mic is off. Enable Mic in the dashboard." : "Talk to MINDI"}
        disabled={micDisabled}
        onPointerDown={(event) => {
          event.stopPropagation();
        }}
        onPointerUp={(event) => {
          event.stopPropagation();
        }}
        onClick={(event) => {
          event.stopPropagation();
          onActivate();
        }}
      >
        <MicGlyph />
      </button>
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
  return (
    <motion.div
      className={`orb-active ${offline ? "orb-active--offline" : ""}`}
      initial={reducedMotion ? false : { opacity: 0, scale: 0.82 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={reducedMotion ? undefined : { opacity: 0, scale: 0.88 }}
      transition={{ type: "spring", stiffness: 100, damping: 20 }}
      layout
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
        <button type="button" className="orb-active__close" onClick={onCancel} aria-label="Dismiss">
          x
        </button>
      </div>
      <div className="orb-active__body">
        {!reducedMotion ? waveform : <span className="orb-active__static-mark" aria-hidden="true" />}
        <p className="orb-active__caption">{caption}</p>
      </div>
    </motion.div>
  );
}

function formatPhase(phase: ActivePhase): string {
  switch (phase) {
    case "waking":
      return "Waking";
    case "greeting":
      return "Hello";
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
