export class WebsocketConnection {
  #socket;
  #ready;

  constructor(endpoint) {
    this.#socket = new WebSocket(endpoint);
    this.#ready = new Promise((resolve, reject) => {
      this.#socket.addEventListener("open", () => resolve(), { once: true });
      this.#socket.addEventListener("error", () => {
        reject(new Error(`Could not connect to WebSocket endpoint: ${endpoint}`));
      }, { once: true });
      this.#socket.addEventListener("close", () => {
        reject(new Error("WebSocket closed before the connection opened."));
      }, { once: true });
    });
  }

  async sendText(text) {
    if (typeof text !== "string") {
      throw new TypeError("Text messages must be strings.");
    }
    await this.#ready;
    this.#assertOpen();
    this.#socket.send(text);
  }

  onText(callback) {
    this.#socket.addEventListener("message", (event) => {
      if (typeof event.data === "string") callback(event.data);
    });
  }

  onOpen(callback) {
    return this.#ready.then(callback);
  }

  async sendBinary(bytes) {
    if (!(bytes instanceof ArrayBuffer) && !ArrayBuffer.isView(bytes) && !(bytes instanceof Blob)) {
      throw new TypeError("Binary messages must be an ArrayBuffer, typed array, DataView, or Blob.");
    }
    await this.#ready;
    this.#assertOpen();
    this.#socket.send(bytes);
  }

  #assertOpen() {
    if (this.#socket.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket connection is not open.");
    }
  }
}
