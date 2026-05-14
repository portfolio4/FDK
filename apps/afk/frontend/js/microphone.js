export class Microphone {
  #context = null;
  #stream = null;
  #source = null;
  #processor = null;
  #generation = 0;
  #muted = false;

  // callback receives an ArrayBuffer of mono, 16 kHz, little-endian PCM16 bytes.
  async startCapture(callback) {
    if (typeof callback !== "function") {
      throw new TypeError("Microphone capture requires an audio callback.");
    }
    this.stopCapture();
    const generation = this.#generation;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone capture is unavailable in this browser.");
    }

    try {
      const context = new AudioContext({ sampleRate: 16_000 });
      this.#context = context;
      await context.resume();
      if (generation !== this.#generation) return false;

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (generation !== this.#generation) {
        stream.getTracks().forEach((track) => track.stop());
        return false;
      }
      this.#stream = stream;
      stream.getAudioTracks().forEach((track) => { track.enabled = !this.#muted; });
      await context.audioWorklet.addModule(new URL("./microphone-processor.js", import.meta.url));
      if (generation !== this.#generation) return false;

      this.#source = context.createMediaStreamSource(stream);
      this.#processor = new AudioWorkletNode(context, "microphone-pcm16", {
        channelCount: 1,
        channelCountMode: "explicit",
      });
      this.#processor.port.postMessage({ type: "set_muted", muted: this.#muted });
      this.#processor.port.onmessage = ({ data }) => {
        // Drop queued chunks while muted so playback cannot reach STT.
        if (generation === this.#generation && !this.#muted) callback(data);
      };
      this.#source.connect(this.#processor);
      this.#processor.connect(context.destination);
      return true;
    } catch (error) {
      if (generation !== this.#generation) return false;
      this.stopCapture();
      throw error;
    }
  }

  setMuted(muted) {
    this.#muted = Boolean(muted);
    this.#stream?.getAudioTracks().forEach((track) => { track.enabled = !this.#muted; });
    this.#processor?.port.postMessage({ type: "set_muted", muted: this.#muted });
  }

  stopCapture() {
    // Invalidate queued audio callbacks and any capture still awaiting permission.
    this.#generation += 1;
    if (this.#processor) {
      this.#processor.port.onmessage = null;
      this.#processor.port.close();
      this.#processor.disconnect();
    }
    this.#source?.disconnect();
    this.#stream?.getTracks().forEach((track) => track.stop());
    if (this.#context && this.#context.state !== "closed") {
      void this.#context.close().catch((error) => console.error("Microphone cleanup failed:", error));
    }
    this.#context = null;
    this.#stream = null;
    this.#source = null;
    this.#processor = null;
  }
}
