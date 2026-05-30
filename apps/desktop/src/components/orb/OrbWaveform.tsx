import { memo } from "react";
import { motion } from "framer-motion";

interface OrbWaveformProps {
  active: boolean;
  level?: number;
}

const BAR_COUNT = 7;

function OrbWaveformInner({ active, level = 0.35 }: OrbWaveformProps) {
  if (!active) {
    return null;
  }

  return (
    <div className="orb-waveform" aria-hidden="true">
      {Array.from({ length: BAR_COUNT }, (_, index) => (
        <motion.span
          key={index}
          className="orb-waveform__bar"
          animate={{
            scaleY: [0.35, 0.55 + level * 0.45, 0.35],
          }}
          transition={{
            duration: 0.9 + index * 0.08,
            repeat: Infinity,
            ease: "easeInOut",
            delay: index * 0.06,
          }}
        />
      ))}
    </div>
  );
}

export const OrbWaveform = memo(OrbWaveformInner);

interface OrbPulseProps {
  show: boolean;
}

function OrbPulseInner({ show }: OrbPulseProps) {
  if (!show) {
    return null;
  }

  return (
    <div className="orb-pulse" aria-hidden="true">
      {[0, 1, 2].map((ring) => (
        <motion.span
          key={ring}
          className="orb-pulse__ring"
          initial={{ opacity: 0.55, scale: 0.6 }}
          animate={{ opacity: 0, scale: 1.8 }}
          transition={{
            duration: 0.75,
            ease: "easeOut",
            delay: ring * 0.12,
          }}
        />
      ))}
    </div>
  );
}

export const OrbPulse = memo(OrbPulseInner);
