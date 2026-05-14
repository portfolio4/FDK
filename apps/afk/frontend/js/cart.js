// Prices are in cents so subtotal and tax calculations avoid fractional dollars.
export const MENU_PRICES = Object.freeze({
  "Classic Cheeseburger": 899,
  "Double Smash": 1149,
  "Vanilla Bean": 499,
  "Rich Chocolate": 549,
  "Fries": 349,
  "Onion Rings": 449,
  "Bottled Water": 199,
  "Coke": 249,
  "Sprite": 249,
  "Ginger Ale": 249,
});

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export class Cart {
  #items = new Map();
  #root;
  #elements;

  constructor(element) {
    this.#root = element;
    this.#elements = {
      items: element.querySelector("#orderItems"),
      subtotal: element.querySelector("#orderSubtotal"),
      tax: element.querySelector("#orderTax"),
      total: element.querySelector("#orderTotal"),
    };
    if (Object.values(this.#elements).some((target) => !target)) {
      throw new Error("Cart UI must contain order items, subtotal, tax, and total elements.");
    }
    this.#render();
  }

  addItems(item_name, quantity) {
    this.#validateItem(item_name);
    this.#validateQuantity(quantity);
    this.#items.set(item_name, (this.#items.get(item_name) ?? 0) + quantity);
    this.#render();
  }

  clear() {
    this.#items.clear();
    this.#render();
  }

  removeItems(item_name, quantity) {
    this.#validateItem(item_name);
    this.#validateQuantity(quantity);
    const remaining = (this.#items.get(item_name) ?? 0) - quantity;
    if (remaining > 0) {
      this.#items.set(item_name, remaining);
    } else {
      this.#items.delete(item_name);
    }
    this.#render();
  }

  removeAllOfItem(item_name) {
    this.#validateItem(item_name);
    this.#items.delete(item_name);
    this.#render();
  }

  #validateItem(item_name) {
    if (!Object.hasOwn(MENU_PRICES, item_name)) {
      throw new Error(`Unknown menu item: ${item_name}`);
    }
  }

  #validateQuantity(quantity) {
    if (!Number.isSafeInteger(quantity) || quantity <= 0) {
      throw new RangeError("Quantity must be a positive integer.");
    }
  }

  #render() {
    const document = this.#root.ownerDocument;
    const rows = document.createDocumentFragment();
    let subtotal = 0;

    for (const [name, quantity] of this.#items) {
      const lineTotal = MENU_PRICES[name] * quantity;
      subtotal += lineTotal;

      const row = document.createElement("li");
      row.className = "flex items-start justify-between gap-sm border-b border-surface-variant pb-sm";
      const label = document.createElement("span");
      label.className = "min-w-0 font-semibold text-on-background";
      label.textContent = `${quantity}x ${name}`;
      const price = document.createElement("span");
      price.className = "flex-shrink-0 tabular-nums text-primary";
      price.textContent = currency.format(lineTotal / 100);
      row.append(label, price);
      rows.append(row);
    }

    if (this.#items.size === 0) {
      const empty = document.createElement("li");
      empty.id = "emptyOrderMessage";
      empty.className = "py-md text-center text-on-surface-variant";
      empty.textContent = "Your order is empty. Items will appear here as you order.";
      rows.append(empty);
    }

    const tax = Math.round(subtotal / 10);
    this.#elements.items.replaceChildren(rows);
    this.#elements.subtotal.textContent = currency.format(subtotal / 100);
    this.#elements.tax.textContent = currency.format(tax / 100);
    this.#elements.total.textContent = currency.format((subtotal + tax) / 100);
  }
}
