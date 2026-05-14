import { BrowserSpeaker } from "./speak.js";
import { Cart } from "./cart.js";
import { Conversation } from "./conversation.js";
import { WebsocketConnection } from "./websocket.js";
import { Microphone } from "./microphone.js";
import { applyAgentMessages } from "./agent_messages.js";

const connection = new WebsocketConnection("ws://127.0.0.1:8001/ws");

const speaker = new BrowserSpeaker();
const microphone = new Microphone();
const cart = new Cart(document.querySelector("#currentOrder"));

const conversation = new Conversation(document.querySelector("#chatContainerWrapper"), { speaker, microphone });
connection.onText((response) => {
  try {
    applyAgentMessages(response, cart, conversation);
  } catch (error) {
    console.error("Invalid agent response:", error);
  }
});
connection.onOpen(() => connection.sendText('{"type":"done_ordering"}'))
  .catch((error) => console.error("Failed to initialize the customer session:", error));

const recordButton = document.querySelector("#recordBtn");
const recordText = document.querySelector("#recordText");
const recordIcon = document.querySelector("#recordIcon");
let isRecording = false;
let captureSession = 0;

function renderCaptureState(recording) {
  isRecording = recording;
  recordText.textContent = recording ? "Done Ordering" : "Tap to Order";
  recordIcon.textContent = recording ? "stop" : "mic";
  recordButton.setAttribute("aria-pressed", String(recording));
  recordButton.classList.toggle("bg-primary", !recording);
  recordButton.classList.toggle("hover:bg-surface-tint", !recording);
  recordButton.classList.toggle("bg-error", recording);
  document.querySelector("#recordingOverlay").classList.toggle("opacity-0", !recording);
  document.querySelector("#chatContainerWrapper").classList.toggle("border-primary", recording);
}

function stopOrdering() {
  captureSession += 1;
  microphone.stopCapture();
  cart.clear();
  renderCaptureState(false);
  connection.sendText('{"type":"done_ordering"}')
    .catch((error) => console.error("Failed to send done_ordering message:", error));
}

recordButton.addEventListener("click", async () => {
  if (isRecording) {
    conversation.clear();
    stopOrdering();
    return;
  }

  recordButton.disabled = true;
  recordText.textContent = "Starting microphone...";
  const session = ++captureSession;
  try {
    conversation.addSystemMessage("Welcome to FreshCuisine Kiosk. What can I get for you today?");
    const started = await microphone.startCapture((audio) => {
      connection.sendBinary(audio).catch((error) => {
        if (session !== captureSession) return;
        console.error("Microphone streaming failed:", error);
        stopOrdering();
        conversation.addSystemMessage("Audio streaming stopped. Check the backend connection and try again.");
      });
    });
    renderCaptureState(started);
  } catch (error) {
    console.error("Microphone capture failed:", error);
    stopOrdering();
    conversation.addSystemMessage(error.name === "NotAllowedError"
      ? "Microphone access was denied. Allow microphone access and try again."
      : "Could not start the microphone. Please try again.");
  } finally {
    recordButton.disabled = false;
  }
});

window.addEventListener("pagehide", stopOrdering);

