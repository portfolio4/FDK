import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { Conversation } from "../js/conversation.js";
import { Microphone } from "../js/microphone.js";
import { BrowserSpeaker } from "../js/speak.js";

class Element {
  children = [];
  classList = { add() {}, remove() {} };
  ownerDocument = { createElement: () => new Element() };
  append(...children) { this.children.push(...children); }
}
const history = new Element();
const root = { querySelector: () => history };
const utterances = [];
globalThis.window = { speechSynthesis: {
  getVoices: () => [{ name: "Test English", lang: "en-US", localService: true, default: true }],
  addEventListener() {},
  speak(utterance) { utterances.push(utterance); },
} };
globalThis.SpeechSynthesisUtterance = class extends EventTarget {
  constructor(text) { super(); this.text = text; }
};

let Processor;
runInNewContext(readFileSync(new URL("../js/microphone-processor.js", import.meta.url), "utf8"), {
  AudioWorkletProcessor: class { port = {}; }, ArrayBuffer, DataView,
  registerProcessor(name, implementation) { Processor = implementation; },
});
let processor;
const tracks = [];
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: {
  async getUserMedia() {
    const track = { enabled: true, stopped: false, stop() { this.stopped = true; } };
    tracks.push(track);
    return { getTracks: () => [track], getAudioTracks: () => [track] };
  },
} } });
globalThis.AudioContext = class {
  state = "running";
  audioWorklet = { async addModule() {} };
  async resume() {}
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  async close() { this.state = "closed"; }
};
globalThis.AudioWorkletNode = class {
  constructor() {
    processor = new Processor();
    const activeProcessor = processor;
    this.port = {
      postMessage: data => activeProcessor.port.onmessage({ data }),
      close() {},
    };
    activeProcessor.port.postMessage = data => this.port.onmessage?.({ data });
  }
  connect() {}
  disconnect() {}
};

const chunks = [];
const microphone = new Microphone();
const conversation = new Conversation(root, { speaker: new BrowserSpeaker(), microphone });
const capture = () => microphone.startCapture(buffer => chunks.push(new Int16Array(buffer)));
const samples = (count, value) => processor.process([[new Float32Array(count).fill(value)]]);
const waitForSpeech = async count => {
  for (let attempt = 0; utterances.length < count; attempt++) {
    assert.ok(attempt < 100, "Speech did not start");
    await new Promise(resolve => setTimeout(resolve, 0));
  }
};

await capture();
samples(1600, 0.5);
assert.ok(chunks.at(-1).some(value => value !== 0));
samples(800, 0.75); // Leave a partial chunk before muting.
const first = conversation.addSystemMessage("First confirmation.");
assert.equal(tracks.at(-1).enabled, false);
await waitForSpeech(1);
assert.equal(utterances[0].text, "First confirmation.");
const chunksBeforeMute = chunks.length;
samples(1600, 0.75);
assert.equal(chunks.length, chunksBeforeMute, "Capture callback ran while muted");
processor.port.postMessage(new Int16Array(1600).fill(24000).buffer);
assert.equal(chunks.length, chunksBeforeMute, "An already queued audio chunk escaped muting");
utterances[0].dispatchEvent(new Event("end"));
await first;
assert.equal(tracks.at(-1).enabled, true);
samples(1600, 0.25);
assert.equal(chunks.length, chunksBeforeMute + 1, "Capture callback did not resume after unmuting");
assert.ok(chunks.at(-1).every(value => value === 8192), "Partial audio leaked across a mute transition");

const failures = [];
const originalError = console.error;
console.error = (...args) => failures.push(args);
try {
  const failed = conversation.addSystemMessage("Playback failure.");
  await waitForSpeech(2);
  utterances[1].dispatchEvent(Object.assign(new Event("error"), { error: "test" }));
  await failed;
  assert.equal(tracks.at(-1).enabled, true, "Playback failure left the microphone muted");
  assert.equal(failures.length, 1);
} finally {
  console.error = originalError;
}

const last = conversation.addSystemMessage("Final confirmation.");
await waitForSpeech(3);
microphone.stopCapture();
assert.equal(tracks.at(-1).stopped, true);
await capture();
assert.equal(tracks.at(-1).enabled, false, "New capture started unmuted during playback");
const activeTrack = tracks.at(-1);
microphone.stopCapture();
utterances[2].dispatchEvent(new Event("end"));
await last;
assert.equal(activeTrack.stopped, true);
assert.equal(activeTrack.enabled, false, "Speech completion reactivated stopped capture");
console.log("PASS: spoken messages, suppressed muted callbacks, mute transitions, failures, and capture lifecycle.");
