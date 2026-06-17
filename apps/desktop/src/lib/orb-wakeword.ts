import * as ort from "onnxruntime-web";

const SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 1280;
const WAKE_THRESHOLD = 0.55;
const WAKE_DEBOUNCE_MS = 2500;

const ASSET_BASE = "/wakeword";

export interface WakeWordDetectorOptions {
  onWake: () => void;
  modelName?: string;
  threshold?: number;
}

export class OpenWakeWordDetector {
  private readonly onWake: () => void;
  private readonly threshold: number;
  private readonly modelName: string;
  private melSession: ort.InferenceSession | null = null;
  private embedSession: ort.InferenceSession | null = null;
  private wakeSession: ort.InferenceSession | null = null;
  private audioContext: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private stream: MediaStream | null = null;
  private pcmQueue: Float32Array = new Float32Array(0);
  private running = false;
  private lastWakeAt = 0;

  constructor(options: WakeWordDetectorOptions) {
    this.onWake = options.onWake;
    this.threshold = options.threshold ?? WAKE_THRESHOLD;
    this.modelName = options.modelName ?? "mindi.onnx";
  }

  private async resolveWakeModelUrl(): Promise<string> {
    const mindi = `${ASSET_BASE}/mindi.onnx`;
    try {
      const response = await fetch(mindi, { method: "HEAD" });
      if (response.ok) {
        return mindi;
      }
    } catch {
      // Fall back to bundled pretrained model until mindi.onnx is trained.
    }
    return `${ASSET_BASE}/hey_jarvis_v0.1.onnx`;
  }

  private async loadSessions(): Promise<void> {
    if (this.melSession && this.embedSession && this.wakeSession) {
      return;
    }
    ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/";
    const [melSession, embedSession, wakeSession] = await Promise.all([
      ort.InferenceSession.create(`${ASSET_BASE}/melspectrogram.onnx`),
      ort.InferenceSession.create(`${ASSET_BASE}/embedding_model.onnx`),
      ort.InferenceSession.create(await this.resolveWakeModelUrl()),
    ]);
    this.melSession = melSession;
    this.embedSession = embedSession;
    this.wakeSession = wakeSession;
  }

  private concatPcm(chunk: Float32Array): void {
    const merged = new Float32Array(this.pcmQueue.length + chunk.length);
    merged.set(this.pcmQueue, 0);
    merged.set(chunk, this.pcmQueue.length);
    this.pcmQueue = merged;
  }

  private async scoreFrame(frame: Float32Array): Promise<number> {
    if (!this.melSession || !this.embedSession || !this.wakeSession) {
      return 0;
    }
    const input = new ort.Tensor("float32", frame, [1, frame.length]);
    const melResult = await this.melSession.run({ input });
    const melOutput = melResult.output ?? melResult[Object.keys(melResult)[0] ?? ""];
    const embedResult = await this.embedSession.run({ input: melOutput });
    const embedOutput = embedResult.output ?? embedResult[Object.keys(embedResult)[0] ?? ""];
    const wakeResult = await this.wakeSession.run({ input: embedOutput });
    const wakeOutput = wakeResult.output ?? wakeResult[Object.keys(wakeResult)[0] ?? ""];
    const data = wakeOutput.data as Float32Array | number[];
    if (!data || data.length === 0) {
      return 0;
    }
    return Number(data[data.length - 1] ?? 0);
  }

  private async consumePcm(): Promise<void> {
    while (this.running && this.pcmQueue.length >= FRAME_SAMPLES) {
      const frame = this.pcmQueue.slice(0, FRAME_SAMPLES);
      this.pcmQueue = this.pcmQueue.slice(FRAME_SAMPLES);
      try {
        const score = await this.scoreFrame(frame);
        if (score >= this.threshold) {
          const now = Date.now();
          if (now - this.lastWakeAt >= WAKE_DEBOUNCE_MS) {
            this.lastWakeAt = now;
            this.onWake();
          }
        }
      } catch {
        // Ignore transient ONNX inference errors and keep listening.
      }
    }
  }

  async start(stream: MediaStream): Promise<void> {
    if (this.running) {
      return;
    }
    await this.loadSessions();
    this.running = true;
    this.stream = stream;
    this.audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    await this.audioContext.audioWorklet.addModule(new URL("../worklets/pcm-processor.ts", import.meta.url));
    const source = this.audioContext.createMediaStreamSource(stream);
    this.workletNode = new AudioWorkletNode(this.audioContext, "pcm-processor");
    this.workletNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!this.running) {
        return;
      }
      this.concatPcm(event.data);
      void this.consumePcm();
    };
    source.connect(this.workletNode);
  }

  async stop(): Promise<void> {
    this.running = false;
    this.pcmQueue = new Float32Array(0);
    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.audioContext) {
      await this.audioContext.close();
      this.audioContext = null;
    }
    this.stream = null;
  }
}

export function playWakeEarcon(): void {
  const context = new AudioContext();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  gain.gain.value = 0.0001;
  oscillator.connect(gain);
  gain.connect(context.destination);
  const now = context.currentTime;
  gain.gain.exponentialRampToValueAtTime(0.08, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.18);
  oscillator.start(now);
  oscillator.stop(now + 0.2);
  oscillator.onended = () => {
    void context.close();
  };
}
