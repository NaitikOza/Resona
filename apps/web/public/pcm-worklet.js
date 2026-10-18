class ResonaPcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.paused = false;
    this.pending = [];
    this.phase = 0;
    this.lastLevel = 0;
    this.port.onmessage = (event) => {
      if (event.data?.type === "pause") this.paused = true;
      if (event.data?.type === "resume") this.paused = false;
      if (event.data?.type === "flush") {
        this.emitPending(true);
        this.port.postMessage({ type: "flushed" });
      }
    };
  }

  emitPending(force = false) {
    while (this.pending.length >= 4096 || (force && this.pending.length > 0)) {
      const length = force ? Math.min(4096, this.pending.length) : 4096;
      const pcm = new Int16Array(this.pending.splice(0, length));
      this.port.postMessage({ type: "audio", pcm, level: this.lastLevel }, [pcm.buffer]);
    }
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input || this.paused) return true;
    const ratio = sampleRate / 16000;
    let sumSquares = 0;
    for (let index = 0; index < input.length; index += 1) sumSquares += input[index] * input[index];
    const level = Math.min(1, Math.sqrt(sumSquares / input.length) * 4);
    this.lastLevel = level;

    let position = this.phase;
    for (; position < input.length; position += ratio) {
      const lower = Math.floor(position);
      const upper = Math.min(input.length - 1, lower + 1);
      const mix = position - lower;
      const value = input[lower] * (1 - mix) + input[upper] * mix;
      this.pending.push(Math.max(-32768, Math.min(32767, Math.round(value * 32767))));
    }
    this.phase = position - input.length;
    this.emitPending();
    return true;
  }
}

registerProcessor("resona-pcm-processor", ResonaPcmProcessor);

