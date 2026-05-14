export class Conversation {
  #history;
  #pendingUserMessage = null;
  #speaker;
  #microphone;

  constructor(element, { speaker = null, microphone = null } = {}) {
    this.#speaker = speaker;
    this.#microphone = microphone;
    this.#history = element.querySelector("#chatHistory");
    if (!this.#history) {
      throw new Error("Conversation UI must contain a chat history element.");
    }
  }

  addSystemMessage(msg) {
    this.#validateMessage(msg);
    const message = this.#createMessage(msg, false);
    this.#history.append(message.element);
    this.#scrollToLatest();
    if (!this.#speaker || !msg.trim()) return Promise.resolve();

    this.#microphone?.setMuted(true);
    return this.#speaker.speak(msg)
      .catch((error) => console.error("System message playback failed:", error))
      .finally(() => this.#microphone?.setMuted(false));
  }

  clear() {
    this.#history.replaceChildren();
    this.#pendingUserMessage = null;
  }

  // Each update replaces the current partial transcript rather than adding a row.
  setPendingUserMessage(msg) {
    this.#validateMessage(msg);
    if (!this.#pendingUserMessage) {
      this.#pendingUserMessage = this.#createMessage("", true);
      this.#pendingUserMessage.bubble.classList.add("motion-safe:animate-pulse");
      this.#history.append(this.#pendingUserMessage.element);
    }
    this.#pendingUserMessage.text = msg;
    this.#pendingUserMessage.bubble.textContent = msg + "...";
    this.#scrollToLatest();
  }

  commitPendingUserMessage() {
    if (!this.#pendingUserMessage) return;
    this.#pendingUserMessage.bubble.textContent = this.#pendingUserMessage.text;
    this.#pendingUserMessage.bubble.classList.remove("motion-safe:animate-pulse");
    this.#pendingUserMessage = null;
    this.#scrollToLatest();
  }

  #validateMessage(msg) {
    if (typeof msg !== "string") {
      throw new TypeError("Conversation messages must be strings.");
    }
  }

  #createMessage(text, isUser) {
    const document = this.#history.ownerDocument;
    const element = document.createElement("li");
    element.className = `mt-sm flex max-w-[85%] flex-shrink-0 flex-col ${
      isUser ? "items-end self-end" : "items-start self-start"
    }`;

    const label = document.createElement("span");
    label.className = `mb-xs font-label-bold text-label-bold text-on-surface-variant ${
      isUser ? "mr-sm" : "ml-sm"
    }`;
    label.textContent = isUser ? "You" : "Assistant";

    const bubble = document.createElement("p");
    bubble.className = `max-w-full whitespace-pre-wrap break-words rounded-xl p-sm font-body-lg text-body-lg ${
      isUser
        ? "rounded-tr-none bg-primary-container text-on-primary-container"
        : "rounded-tl-none bg-surface-variant text-on-surface-variant"
    }`;
    bubble.textContent = text;

    element.append(label, bubble);
    return { element, bubble, text };
  }

  #scrollToLatest() {
    this.#history.scrollTop = this.#history.scrollHeight;
  }
}
