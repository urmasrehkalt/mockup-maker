// Wireframe renderer: turns a validated component tree into DOM.
//
// Everything goes through h(), which inserts text as text nodes, so a mockup
// cannot inject markup or run scripts whatever its text says. Unknown
// component types (which the server rejects anyway) render as a labelled box.
// Every element carries data-component-id, so criteria can point at it.

import { h } from "../dom.js";

const RENDERERS = {
  header: (c) => h("div", { class: "wf-header" },
    h("span", { class: "wf-brand" }, c.text ?? ""), h("div", { class: "wf-header-items" }, kids(c))),
  nav: (c) => h("div", { class: "wf-nav" }, (c.items ?? []).map((item) => h("span", { class: "wf-link" }, item))),
  heading: (c) => h("div", { class: `wf-heading wf-h${c.level ?? 2}` }, c.text),
  text: (c) => h("p", { class: "wf-text" }, c.text),
  image: (c) => h("div", { class: "wf-image" }, h("span", {}, c.text)),
  card: (c) => h("div", { class: "wf-card" },
    c.text ? h("div", { class: "wf-card-title" }, c.text) : null,
    c.secondary ? h("div", { class: "wf-muted" }, c.secondary) : null, kids(c)),
  grid: (c) => h("div", { class: "wf-grid", style: `--wf-cols: ${c.columns ?? 3}` }, kids(c)),
  price_card: (c) => h("div", { class: "wf-card wf-price" },
    h("div", { class: "wf-card-title" }, c.text),
    h("div", { class: "wf-price-value" }, c.secondary ?? ""),
    c.items ? h("ul", { class: "wf-checks" }, c.items.map((i) => h("li", {}, i))) : null, kids(c)),
  list: (c) => h("ul", { class: "wf-list" }, (c.items ?? []).map((i) => h("li", {}, i))),
  table: (c) => h("table", { class: "wf-table" },
    h("thead", {}, h("tr", {}, (c.items ?? []).map((col) => h("th", {}, col)))),
    h("tbody", {}, (c.rows ?? []).map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell)))))),
  form: (c) => h("div", { class: "wf-form" }, c.text ? h("div", { class: "wf-card-title" }, c.text) : null, kids(c)),
  input: (c) => input(c),
  button: (c) => h("span", { class: `wf-button wf-${c.variant ?? "primary"}` }, c.text),
  footer: (c) => h("div", { class: "wf-footer" }, c.text ? h("span", {}, c.text) : null, kids(c)),
  section: (c) => h("div", { class: "wf-section" }, c.text ? h("div", { class: "wf-section-title" }, c.text) : null, kids(c)),
  note: (c) => h("div", { class: "wf-note" }, c.text),
  notice: (c) => h("div", { class: `wf-notice wf-${c.variant ?? "info"}` },
    h("span", { class: "wf-notice-icon", "aria-hidden": "true" }, NOTICE_ICONS[c.variant ?? "info"]), c.text),
  steps: (c) => h("ol", { class: "wf-steps" }, (c.items ?? []).map((i) => h("li", {}, i))),
};

const NOTICE_ICONS = { info: "i", success: "✓", warning: "!", error: "×" };

function input(c) {
  const label = h("span", { class: "wf-label" }, c.text, c.required ? h("span", { class: "wf-required" }, " *") : null);
  if (c.variant === "checkbox") {
    return h("div", { class: "wf-input wf-checkbox" }, h("span", { class: "wf-box", "aria-hidden": "true" }), label);
  }
  const field = h("span", { class: `wf-field ${c.variant === "textarea" ? "wf-textarea" : ""}` },
    c.secondary ?? "", c.variant === "select" ? h("span", { class: "wf-caret", "aria-hidden": "true" }, "▾") : null);
  return h("div", { class: "wf-input" }, label, field);
}

function kids(c) {
  return (c.children ?? []).map(component);
}

function component(c) {
  const render = RENDERERS[c.type] ?? ((x) => h("div", { class: "wf-unknown" }, `[${x.type}]`));
  const el = render(c);
  el.dataset.componentId = c.id;
  el.dataset.componentType = c.type;
  return el;
}

/** Render a whole view. `viewport` is "desktop" or "mobile". */
export function renderTree(tree, { viewport = "desktop" } = {}) {
  return h("div", { class: `wf wf-${viewport}`, role: "img", "aria-label": tree.title },
    tree.components.map(component));
}

/** A small, non-interactive preview of a view. */
export function thumbnail(tree) {
  return h("div", { class: "wf-thumb", "aria-hidden": "true" }, h("div", { class: "wf-thumb-inner" }, renderTree(tree)));
}
