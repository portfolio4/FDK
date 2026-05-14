// At 16 kHz, 1,600 samples form a 100 ms chunk of mono PCM16 audio.
class MicrophoneProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new ArrayBuffer(1_600 * 2);
    this.samples = new DataView(this.buffer);
    this.position = 0;
    this.muted = false;
    this.port.onmessage = ({ data }) => {
      if (data.type !== "set_muted" || this.muted === data.muted) return;
      this.muted = data.muted;
      // Discard partial chunks at transitions so speaker audio cannot linger.
      this.position = 0;
    };
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;

    for (const value of input) {
      const sample = this.muted ? 0 : Math.max(-1, Math.min(1, value));
      const pcm = Math.round(sample < 0 ? sample * 0x8000 : sample * 0x7fff);
      this.samples.setInt16(this.position * 2, pcm, true);
      if (++this.position === 1_600) {
        this.port.postMessage(this.buffer, [this.buffer]);
        this.buffer = new ArrayBuffer(1_600 * 2);
        this.samples = new DataView(this.buffer);
        this.position = 0;
      }
    }
    // Outputs remain silent; microphone audio is never played through speakers.
    return true;
  }
}

registerProcessor("microphone-pcm16", MicrophoneProcessor);
