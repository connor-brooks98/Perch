class TestStyle {
  constructor() { this.properties = new Map(); }
  setProperty(name, value) { this.properties.set(name, String(value)); }
}

export class TestElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.dataset = {};
    this.style = new TestStyle();
    this.listeners = new Map();
    this.className = "";
    this.disabled = false;
    this.value = "";
    this.checked = false;
    this.inert = false;
    this.open = false;
    this._text = "";
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  append(...children) {
    for (const child of children) {
      child.parentNode = this;
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this._text = "";
    this.append(...children);
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }

  focus() { globalThis.document.activeElement = this; }

  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }

  get isConnected() {
    if (this === globalThis.document?.body) return true;
    return Boolean(this.parentNode?.isConnected);
  }

  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) || [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }

  async dispatch(name, init = {}) {
    const event = {
      target: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...init,
    };
    await Promise.all((this.listeners.get(name) || []).map((callback) => callback(event)));
    return event;
  }

  matches(selector) {
    if (selector.startsWith("#")) return this.id === selector.slice(1);
    if (selector.startsWith(".")) return this.className.split(/\s+/).includes(selector.slice(1));
    if (selector === "[data-inline-error]") return this.dataset.inlineError !== undefined;
    if (selector.startsWith("[data-") && selector.endsWith("]")) {
      const key = selector.slice(6, -1).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      return this.dataset[key] !== undefined;
    }
    return this.tagName === selector.toUpperCase();
  }

  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }

  querySelectorAll(selector) {
    const found = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.matches(selector)) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }
}

export function installDom() {
  const body = new TestElement("body");
  const view = new TestElement("main");
  view.id = "view";
  const status = new TestElement("p");
  status.id = "connection-status";
  body.append(view, status);
  const document = {
    body,
    activeElement: body,
    createElement: (tagName) => new TestElement(tagName),
    querySelector: (selector) => body.matches(selector) ? body : body.querySelector(selector),
  };
  globalThis.document = document;
  return {document, view, status};
}

export function detection(overrides = {}) {
  return {
    id: 1,
    captured_at: "2026-07-13T14:00:00Z",
    thumbnail: "thumbs/1.jpg",
    display_image: "images/1.jpg",
    confidence: .91,
    favorite: false,
    effective_species: {common_name: "Blue Jay", scientific: "Cyanocitta cristata"},
    species_key: "sci:cyanocitta cristata",
    is_first_visit: false,
    ...overrides,
  };
}

export function todayData(overrides = {}) {
  const latest = detection();
  return {
    greeting: "Good morning from the feeder.",
    latest,
    visits_today: 1,
    species_today: 1,
    busiest_hour: 10,
    hourly_activity: Array(24).fill(0),
    recent: [detection()],
    has_more: false,
    ...overrides,
  };
}

export function flushTasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
