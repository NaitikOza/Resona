export interface RecorderFrame {
  sequence: number;
  startMs: number;
  endMs: number;
  pcm: Int16Array;
}

export type RecorderState = "idle" | "recording" | "paused" | "stopped";

export class PcmRecorder {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private sequence = 0;
  private sampleCount = 0;
  private state: RecorderState = "idle";
  private flushResolve: (() => void) | null = null;

  async start(
    onFrame: (frame: RecorderFrame) => void,
    onLevel: (level: number) => void,
    deviceId?: string,
  ): Promise<void> {
    if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
      throw new Error("Microphone access requires localhost or HTTPS.");
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser does not expose microphone capture.");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      },
      video: false,
    });
    this.context = createCaptureContext();
    await this.context.audioWorklet.addModule("/pcm-worklet.js");
    if (this.context.state === "suspended") await this.context.resume();
    this.source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "resona-pcm-processor");
    this.node.port.onmessage = (
      event: MessageEvent<
        | { type: "audio"; pcm: Int16Array; level: number }
        | { type: "flushed" }
      >,
    ) => {
      if (event.data.type === "flushed") {
        this.flushResolve?.();
        this.flushResolve = null;
        return;
      }
      if (this.state === "idle" || this.state === "stopped") return;
      const pcm = new Int16Array(event.data.pcm);
      const startMs = Math.round((this.sampleCount / 16_000) * 1000);
      this.sampleCount += pcm.length;
      const endMs = Math.round((this.sampleCount / 16_000) * 1000);
      onLevel(event.data.level);
      onFrame({ sequence: this.sequence++, startMs, endMs, pcm });
    };
    this.source.connect(this.node);
    const silent = this.context.createGain();
    silent.gain.value = 0;
    this.node.connect(silent).connect(this.context.destination);
    this.state = "recording";
  }

  pause(): void {
    if (this.state === "recording") {
      this.state = "paused";
      this.node?.port.postMessage({ type: "pause" });
    }
  }

  resume(): void {
    if (this.state === "paused") {
      this.state = "recording";
      this.node?.port.postMessage({ type: "resume" });
    }
  }

  async stop(): Promise<void> {
    // Quiesce the input before asking the worklet to flush so no new partial
    // buffer can be created between the flush acknowledgement and teardown.
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.node && this.state !== "stopped") {
      await new Promise<void>((resolve) => {
        const timeout = window.setTimeout(resolve, 500);
        this.flushResolve = () => {
          window.clearTimeout(timeout);
          resolve();
        };
        this.node?.port.postMessage({ type: "flush" });
      });
    }
    this.state = "stopped";
    this.node?.disconnect();
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.node = null;
    this.source = null;
    this.stream = null;
    this.context = null;
  }
}

function createCaptureContext(): AudioContext {
  try {
    // Native Web Audio resampling provides a cleaner speech signal than
    // decimating the hardware-rate stream inside the worklet.
    return new AudioContext({ sampleRate: 16_000, latencyHint: "interactive" });
  } catch {
    return new AudioContext({ latencyHint: "interactive" });
  }
}

export function packAudioFrame(frame: RecorderFrame): ArrayBuffer {
  const output = new ArrayBuffer(12 + frame.pcm.byteLength);
  const view = new DataView(output);
  view.setUint32(0, frame.sequence, true);
  view.setUint32(4, frame.startMs, true);
  view.setUint32(8, frame.endMs, true);
  new Int16Array(output, 12).set(frame.pcm);
  return output;
}

export async function prepareAudioUpload(file: File): Promise<File> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await file.arrayBuffer());
    const samples = await resampleToMono(decoded, 16_000);
    const baseName = file.name.replace(/\.[^.]+$/, "") || "recording";
    return new File([encodePcm16Wav(samples, 16_000)], `${baseName}.wav`, {
      type: "audio/wav",
    });
  } catch {
    throw new Error("We couldn't read that audio file. Choose a WAV or MP3 file and try again.");
  } finally {
    if (context.state !== "closed") await context.close();
  }
}

async function resampleToMono(buffer: AudioBuffer, targetRate: number): Promise<Float32Array> {
  try {
    const outputLength = Math.max(1, Math.ceil(buffer.duration * targetRate));
    const renderer = new OfflineAudioContext(1, outputLength, targetRate);
    const mono = renderer.createBuffer(1, buffer.length, buffer.sampleRate);
    const target = mono.getChannelData(0);
    for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
      const source = buffer.getChannelData(channel);
      for (let index = 0; index < source.length; index += 1) {
        target[index] += source[index] / buffer.numberOfChannels;
      }
    }
    const node = renderer.createBufferSource();
    node.buffer = mono;
    node.connect(renderer.destination);
    node.start();
    const rendered = await renderer.startRendering();
    return new Float32Array(rendered.getChannelData(0));
  } catch {
    return resampleLinear(buffer, targetRate);
  }
}

function resampleLinear(buffer: AudioBuffer, targetRate: number): Float32Array {
  const outputLength = Math.max(1, Math.round(buffer.duration * targetRate));
  const output = new Float32Array(outputLength);
  const ratio = buffer.sampleRate / targetRate;

  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const position = outputIndex * ratio;
    const lower = Math.min(buffer.length - 1, Math.floor(position));
    const upper = Math.min(buffer.length - 1, lower + 1);
    const mix = position - lower;
    let sample = 0;
    for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
      const data = buffer.getChannelData(channel);
      sample += data[lower] * (1 - mix) + data[upper] * mix;
    }
    output[outputIndex] = sample / buffer.numberOfChannels;
  }

  return output;
}

export function encodePcm16Wav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const output = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(output);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);

  samples.forEach((sample, index) => {
    const limited = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, limited < 0 ? limited * 0x8000 : limited * 0x7fff, true);
  });
  return output;
}

export function recordedFramesToWav(frames: Int16Array[], sampleRate = 16_000): ArrayBuffer {
  const sampleCount = frames.reduce((total, frame) => total + frame.length, 0);
  const output = new ArrayBuffer(44 + sampleCount * 2);
  const view = new DataView(output);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + sampleCount * 2, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, sampleCount * 2, true);
  let offset = 44;
  for (const frame of frames) {
    for (const sample of frame) {
      view.setInt16(offset, sample, true);
      offset += 2;
    }
  }
  return output;
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

