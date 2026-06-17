/// <reference lib="webworker" />

class PcmProcessor extends AudioWorkletProcessor {
  process(inputs: Float32Array[][]) {
    const input = inputs[0]?.[0];
    if (!input || input.length === 0) {
      return true;
    }
    this.port.postMessage(input.slice());
    return true;
  }
}

registerProcessor("pcm-processor", PcmProcessor);
