import { describe, expect, it } from "vitest";
import { formatDuration, titleCase } from "@/lib/format";
import { encodePcm16Wav, packAudioFrame } from "@/lib/audio";

describe("format utilities", () => {
  it("formats audio-relative timestamps", () => {
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(65_999)).toBe("01:05");
  });

  it("turns internal labels into readable text", () => {
    expect(titleCase("IN_PROGRESS")).toBe("In Progress");
  });
});

describe("PCM transport", () => {
  it("packages the stable binary header before PCM16 samples", () => {
    const packed = packAudioFrame({
      sequence: 7,
      startMs: 250,
      endMs: 500,
      pcm: new Int16Array([100, -100, 42]),
    });
    const header = new DataView(packed);
    expect(header.getUint32(0, true)).toBe(7);
    expect(header.getUint32(4, true)).toBe(250);
    expect(header.getUint32(8, true)).toBe(500);
    expect(Array.from(new Int16Array(packed, 12))).toEqual([100, -100, 42]);
  });

  it("encodes browser-decoded audio as a standard WAV", () => {
    const wav = encodePcm16Wav(new Float32Array([0, 1, -1]), 16_000);
    const view = new DataView(wav);
    const text = (offset: number, length: number) =>
      String.fromCharCode(...new Uint8Array(wav, offset, length));
    expect(text(0, 4)).toBe("RIFF");
    expect(text(8, 4)).toBe("WAVE");
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getInt16(46, true)).toBe(32_767);
    expect(view.getInt16(48, true)).toBe(-32_768);
  });
});

