import assert from "node:assert/strict";
import { Cart } from "../js/cart.js";
import { Conversation } from "../js/conversation.js";
import { applyAgentMessages } from "../js/agent_messages.js";
import { WebsocketConnection } from "../js/websocket.js";

// A small DOM fixture exercises the real Cart and Conversation renderers.
class Element {
  children = [];
  textContent = "";
  classList = { add() {}, remove() {} };
  constructor(document) { this.ownerDocument = document; }
  append(...children) { this.children.push(...children.flatMap(child => child.fragment ? child.children : [child])); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
}
const document = {
  createElement() { return new Element(this); },
  createDocumentFragment() { const fragment = new Element(this); fragment.fragment = true; return fragment; },
};
const elements = Object.fromEntries(["orderItems", "orderSubtotal", "orderTax", "orderTotal", "chatHistory"]
  .map(id => [id, document.createElement()]));
const root = { ownerDocument: document, querySelector(selector) { return elements[selector.slice(1)]; } };
const cart = new Cart(root);
const conversation = new Conversation(root);
const apply = (...messages) => applyAgentMessages(JSON.stringify({ messages }), cart, conversation);
apply({ type: "Cart.addItems", item_name: "Classic Cheeseburger", quantity: 2 },
  { type: "Conversation.addSystemMessage", msg: "Two cheeseburgers added." });
assert.equal(elements.orderSubtotal.textContent, "$17.98");
assert.equal(elements.orderTax.textContent, "$1.80");
assert.equal(elements.orderTotal.textContent, "$19.78");
assert.equal(elements.chatHistory.children[0].children[1].textContent, "Two cheeseburgers added.");
apply({ type: "Conversation.addSystemMessage", msg: "One classic cheeseburger costs $8.99." });
assert.equal(elements.orderSubtotal.textContent, "$17.98");
apply({ type: "Cart.removeItems", item_name: "Classic Cheeseburger", quantity: 1 });
assert.equal(elements.orderTotal.textContent, "$9.89");
apply({ type: "Cart.removeAllOfItem", item_name: "Classic Cheeseburger" });
assert.equal(elements.orderTotal.textContent, "$0.00");
apply({ type: "Cart.addItems", item_name: "Fries", quantity: 1 }, { type: "Cart.clear" });
assert.equal(elements.orderSubtotal.textContent, "$0.00");
assert.throws(() => apply({ type: "Cart.addItems", item_name: "Fries", quantity: 1 }, { type: "eval" }));
assert.equal(elements.orderSubtotal.textContent, "$0.00", "Invalid batches must not partially change the cart");
assert.throws(() => apply({ type: "Cart.addItems", item_name: "Unknown", quantity: 1 }));
assert.throws(() => apply({ type: "Cart.addItems", item_name: "Fries", quantity: 0 }));
assert.throws(() => apply({ type: "Cart.addItems", item_name: "Fries", quantity: null }));
assert.throws(() => apply({ type: "Cart.addItems", item_name: null, quantity: 1 }));
assert.throws(() => apply({ type: "Conversation.addSystemMessage", msg: null }));
assert.throws(() => apply({ type: "Cart.addItems", item_name: "Fries", quantity: 1, msg: "unexpected" }));

const historyLength = elements.chatHistory.children.length;
apply({ type: "Conversation.setPendingUserMessage", msg: "One cheeseburger" });
apply({ type: "Conversation.setPendingUserMessage", msg: "One cheeseburger and fries" });
assert.equal(elements.chatHistory.children.length, historyLength + 1);
const userMessage = elements.chatHistory.children.at(-1);
assert.equal(userMessage.children[0].textContent, "You");
assert.equal(userMessage.children[1].textContent, "One cheeseburger and fries...");
apply({ type: "Conversation.commitPendingUserMessage" });
assert.equal(userMessage.children[1].textContent, "One cheeseburger and fries");
apply({ type: "Conversation.setPendingUserMessage", msg: "Also a Coke" });
assert.equal(elements.chatHistory.children.length, historyLength + 2);
assert.equal(userMessage.children[1].textContent, "One cheeseburger and fries");
assert.throws(() => apply({ type: "Conversation.setPendingUserMessage", msg: 123 }));
assert.throws(() => apply({ type: "Conversation.commitPendingUserMessage", msg: "unexpected" }));
conversation.clear();
assert.equal(elements.chatHistory.children.length, 0);
conversation.commitPendingUserMessage();
assert.equal(elements.chatHistory.children.length, 0);
conversation.setPendingUserMessage("A new customer");
assert.equal(elements.chatHistory.children.length, 1);
conversation.clear();
apply({ type: "Conversation.addSystemMessage", msg: "Welcome!" });
assert.equal(elements.chatHistory.children.length, 1);
assert.equal(elements.chatHistory.children[0].children[1].textContent, "Welcome!");

let socket;
globalThis.WebSocket = class extends EventTarget {
  static OPEN = 1;
  readyState = 0;
  sent = [];
  constructor() { super(); socket = this; }
  send(message) { this.sent.push(message); }
};
const connection = new WebsocketConnection("ws://127.0.0.1:8001/ws");
const startup = connection.onOpen(() => connection.sendText('{"type":"done_ordering"}'));
await Promise.resolve();
assert.deepEqual(socket.sent, [], "Startup message must wait for the connection to open");
socket.readyState = WebSocket.OPEN;
socket.dispatchEvent(new Event("open"));
await startup;
assert.deepEqual(socket.sent, ['{"type":"done_ordering"}']);
connection.onText(response => applyAgentMessages(response, cart, conversation));
socket.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ messages: [
  { type: "Cart.addItems", item_name: "Coke", quantity: 1 },
] }) }));
assert.equal(elements.orderSubtotal.textContent, "$2.49");
socket.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ messages: [
  { type: "Cart.addItems", item_name: "Classic Cheeseburger", quantity: 1, msg: null },
  { type: "Conversation.addSystemMessage", item_name: null, quantity: null, msg: "One cheeseburger added." },
] }) }));
assert.equal(elements.orderSubtotal.textContent, "$11.48");
assert.equal(elements.chatHistory.children.at(-1).children[1].textContent, "One cheeseburger added.");
socket.dispatchEvent(new MessageEvent("message", { data: new Uint8Array([1]) }));
assert.equal(elements.orderSubtotal.textContent, "$11.48");
console.log("PASS: all cart actions, conversation-only prices, atomic validation, and incoming WebSocket JSON.");
