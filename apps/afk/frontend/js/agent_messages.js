import { MENU_PRICES } from "./cart.js";

export function applyAgentMessages(response, cart, conversation) {
  const batch = typeof response === "string" ? JSON.parse(response) : response;
  if (!batch || !Array.isArray(batch.messages) || batch.messages.length === 0 || batch.messages.length > 64) {
    throw new Error("Invalid agent response.");
  }

  // Validate the entire response before mutating the UI.
  for (const message of batch.messages) {
    if (!message || typeof message !== "object") throw new Error("Invalid agent message.");
    let fields;
    switch (message.type) {
      case "Cart.addItems":
      case "Cart.removeItems":
        fields = ["type", "item_name", "quantity"];
        if (!Number.isSafeInteger(message.quantity) || message.quantity <= 0) {
          throw new Error("Invalid cart quantity.");
        }
        break;
      case "Cart.removeAllOfItem":
        fields = ["type", "item_name"];
        break;
      case "Cart.clear":
      case "Conversation.commitPendingUserMessage":
        fields = ["type"];
        break;
      case "Conversation.addSystemMessage":
      case "Conversation.setPendingUserMessage":
        fields = ["type", "msg"];
        if (typeof message.msg !== "string") throw new Error("Invalid conversation message.");
        break;
      default:
        throw new Error("Unsupported agent action.");
    }
    // Structured agent output includes unused action fields as null.
    const populatedFields = Object.keys(message).filter(field => message[field] !== null);
    if (populatedFields.length !== fields.length || fields.some(field => !populatedFields.includes(field))) {
      throw new Error("Invalid agent action fields.");
    }
    if (fields.includes("item_name") && !Object.hasOwn(MENU_PRICES, message.item_name)) {
      throw new Error("Unknown menu item.");
    }
  }

  for (const message of batch.messages) {
    switch (message.type) {
      case "Cart.addItems": cart.addItems(message.item_name, message.quantity); break;
      case "Cart.removeItems": cart.removeItems(message.item_name, message.quantity); break;
      case "Cart.removeAllOfItem": cart.removeAllOfItem(message.item_name); break;
      case "Cart.clear": cart.clear(); break;
      case "Conversation.addSystemMessage": conversation.addSystemMessage(message.msg); break;
      case "Conversation.setPendingUserMessage": conversation.setPendingUserMessage(message.msg); break;
      case "Conversation.commitPendingUserMessage": conversation.commitPendingUserMessage(); break;
    }
  }
}
