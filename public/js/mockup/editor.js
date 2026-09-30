// Manual mockup editor: palette, live canvas, inspector. Works without the AI.
// Drag a palette item onto the canvas (or click it to add after the selection),
// click a component to edit it, drag components to move them. Saving creates a
// new version on the server, which checks the tree again.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { renderTree } from "./render.js";
import * as ops from "./tree-ops.js";

const DEFAULTS = {
  header: { text: "Teenuse nimi", children: null },
  nav: { items: ["Avaleht", "Teenused", "Kontakt"] },
  heading: { text: "Pealkiri", level: 2 },
  text: { text: "Lühike tekst." },
  image: { text: "Pilt" },
  card: { text: "Kaardi pealkiri", secondary: "Lühike kirjeldus." },
  grid: { columns: 3 },
  price_card: { text: "Pakett", secondary: "29 € / kuu", items: ["Omadus 1", "Omadus 2"] },
  list: { items: ["Punkt 1", "Punkt 2"] },
  table: { items: ["Veerg 1", "Veerg 2"], rows: [["…", "…"]] },
  form: {},
  input: { text: "Väli", variant: "text" },
  button: { text: "Nupp", variant: "primary" },
  footer: { text: "© Ettevõte" },
  section: { text: null },
  note: { text: "Märkus" },
  notice: { text: "Teade", variant: "info" },
  steps: { items: ["Samm 1", "Samm 2", "Samm 3"] },
};

// Which fields the inspector offers per type, and their input kind.
const FIELDS = {
  text: { kind: "text", types: ["header", "heading", "text", "image", "card", "price_card", "input", "button", "footer", "section", "note", "notice", "form"] },
  secondary: { kind: "text", types: ["card", "price_card", "input"] },
  items: { kind: "lines", types: ["nav", "list", "table", "price_card", "steps"] },
  rows: { kind: "rows", types: ["table"] },
  level: { kind: "choice", types: ["heading"], options: [1, 2, 3] },
  variant: { kind: "choice", types: ["button", "input", "notice"] },
  required: { kind: "check", types: ["input"] },
  columns: { kind: "choice", types: ["grid"], options: [1, 2, 3, 4] },
};
const VARIANTS = {
  button: ["primary", "secondary", "link"],
  input: ["text", "email", "password", "number", "date", "select", "checkbox", "textarea"],
  notice: ["info", "success", "warning", "error"],
};

// A new component with sample content. A grid and a form must have children to be
// valid, so they start with some; `given` keeps the new ids unique among themselves.
function blank(tree, type, given = new Set()) {
  const node = { id: ops.newId(tree, type, given), type, ...structuredClone(DEFAULTS[type]) };
  given.add(node.id);
  if (type === "grid") node.children = [blank(tree, "card", given), blank(tree, "card", given)];
  if (type === "form") node.children = [blank(tree, "input", given), blank(tree, "button", given)];
  return node;
}

/**
 * @param mockup   { id, title, version, tree }
 * @param options  { projectId, sharedWith: [story keys], onSaved }
 */
export function openMockupEditor(mockup, { projectId, sharedWith = [], onSaved }) {
  const tree = structuredClone(mockup.tree);
  let selected = null;
  let dirty = false;

  const canvas = h("div", { class: "editor-canvas" });
  const inspector = h("aside", { class: "inspector" });
  const status = h("div", { class: "form-status" });
  const titleInput = h("input", { type: "text", maxlength: 120, "aria-label": t("mockup.view_title") });
  titleInput.value = tree.title;
  titleInput.addEventListener("input", () => { tree.title = titleInput.value; dirty = true; });

  const changed = () => { dirty = true; draw(); };

  function add(type) {
    const node = blank(tree, type);
    const target = selected ? ops.locate(tree, selected) : null;
    ops.place(tree, node, selected, { into: target && ops.CONTAINERS.has(target.node.type) });
    selected = node.id;
    changed();
  }

  const palette = h("aside", { class: "palette" },
    h("h3", {}, t("editor.palette")),
    h("p", { class: "hint" }, t("editor.palette_hint")),
    h("ul", {}, Object.keys(DEFAULTS).map((type) => {
      const item = h("button", { type: "button", class: "palette-item", draggable: "true", onclick: () => add(type) },
        t(`component.${type}`));
      item.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/plain", `new:${type}`));
      return h("li", {}, item);
    })));

  function draw() {
    const view = renderTree(tree);
    view.querySelectorAll("[data-component-id]").forEach((el) => {
      const id = el.dataset.componentId;
      el.draggable = true;
      if (id === selected) el.classList.add("wf-selected");
      el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); selected = id; draw(); });
      el.addEventListener("dragstart", (e) => { e.stopPropagation(); e.dataTransfer.setData("text/plain", `move:${id}`); });
      el.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); el.classList.add("wf-drop"); });
      el.addEventListener("dragleave", () => el.classList.remove("wf-drop"));
      el.addEventListener("drop", (e) => {
        e.preventDefault();
        e.stopPropagation();
        el.classList.remove("wf-drop");
        drop(e.dataTransfer.getData("text/plain"), id);
      });
    });
    mount(canvas, view);
    drawInspector();
  }

  function drop(data, targetId) {
    const [what, value] = data.split(":");
    const target = targetId ? ops.locate(tree, targetId) : null;
    const into = Boolean(target && ops.CONTAINERS.has(target.node.type));
    if (what === "new" && DEFAULTS[value]) {
      const node = blank(tree, value);
      if (ops.place(tree, node, targetId, { into })) selected = node.id;
    } else if (what === "move" && value) {
      ops.move(tree, value, targetId, { into });
      selected = value;
    }
    changed();
  }
  canvas.addEventListener("dragover", (e) => e.preventDefault());
  canvas.addEventListener("drop", (e) => { e.preventDefault(); drop(e.dataTransfer.getData("text/plain"), null); });

  function drawInspector() {
    const at = selected ? ops.locate(tree, selected) : null;
    if (!at) {
      mount(inspector, h("h3", {}, t("editor.inspector")), h("p", { class: "hint" }, t("editor.select_hint")));
      return;
    }
    const node = at.node;
    const fields = Object.entries(FIELDS).filter(([, spec]) => spec.types.includes(node.type)).map(([name, spec]) => field(node, name, spec));
    mount(inspector,
      h("h3", {}, t(`component.${node.type}`)),
      h("p", { class: "hint" }, `id: ${node.id}`),
      fields,
      h("div", { class: "inspector-actions" },
        h("button", { type: "button", class: "small", onclick: () => { ops.shift(tree, node.id, -1); changed(); } }, `↑ ${t("editor.up")}`),
        h("button", { type: "button", class: "small", onclick: () => { ops.shift(tree, node.id, 1); changed(); } }, `↓ ${t("editor.down")}`),
        h("button", { type: "button", class: "small", onclick: () => {
          const copy = ops.copyWithNewIds(tree, node);
          ops.place(tree, copy, node.id);
          selected = copy.id;
          changed();
        } }, t("editor.duplicate")),
        h("button", { type: "button", class: "small danger", onclick: () => { ops.remove(tree, node.id); selected = null; changed(); } },
          t("editor.delete"))));
  }

  // One inspector field; edits apply to the working copy and redraw the canvas.
  function field(node, name, spec) {
    const label = t(`field.${name}.${node.type}`) === `field.${name}.${node.type}` ? t(`field.${name}`) : t(`field.${name}.${node.type}`);
    const update = (value) => { node[name] = value; dirty = true; mount(canvas); draw(); };
    let input;
    if (spec.kind === "text") {
      input = h("input", { type: "text", maxlength: 300 });
      input.value = node[name] ?? "";
      input.addEventListener("change", () => update(input.value.trim() || null));
    } else if (spec.kind === "lines" || spec.kind === "rows") {
      input = h("textarea", { rows: 4 });
      input.value = spec.kind === "rows" ? (node.rows ?? []).map((r) => r.join(" | ")).join("\n") : (node[name] ?? []).join("\n");
      input.addEventListener("change", () => {
        const lines = input.value.split("\n").map((l) => l.trim()).filter(Boolean);
        update(spec.kind === "rows" ? lines.map((l) => l.split("|").map((c) => c.trim())) : lines);
      });
    } else if (spec.kind === "check") {
      input = h("input", { type: "checkbox", checked: Boolean(node[name]) });
      input.addEventListener("change", () => update(input.checked));
    } else {
      const options = spec.options ?? VARIANTS[node.type];
      input = h("select", {}, options.map((o) => h("option", { value: o }, t(`variant.${o}`) === `variant.${o}` ? String(o) : t(`variant.${o}`))));
      input.value = String(node[name] ?? options[0]);
      input.addEventListener("change", () => update(typeof options[0] === "number" ? Number(input.value) : input.value));
    }
    return h("label", { class: "stacked" }, label,
      spec.kind === "rows" ? h("span", { class: "hint" }, t("field.rows_hint")) : null, input);
  }

  const dialog = h("dialog", { class: "editor mockup-editor", "aria-label": t("editor.mockup_title") });
  const close = () => {
    if (dirty && !confirm(t("editor.discard_changes"))) return;
    dialog.close();
    dialog.remove();
  };
  async function save() {
    mount(status);
    try {
      await api.saveMockupVersion(projectId, mockup.id, tree);
      dirty = false;
      dialog.close();
      dialog.remove();
      await onSaved?.();
    } catch (error) {
      mount(status, notice(error.status === 422 ? `${t("editor.invalid_tree")} ${error.message}` : errorText(error), "error"));
    }
  }
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });

  mount(dialog,
    h("div", { class: "viewer-head" },
      h("h2", {}, t("editor.mockup_title")), titleInput,
      h("button", { type: "button", class: "small", onclick: close }, t("editor.cancel")),
      h("button", { type: "button", class: "small primary", onclick: save }, t("editor.save_version"))),
    sharedWith.length > 1 ? notice(t("editor.shared", { keys: sharedWith.join(", ") })) : null,
    status,
    h("div", { class: "editor-body" }, palette, h("div", { class: "wf-stage" }, canvas), inspector));
  document.body.append(dialog);
  draw();
  dialog.showModal();
}
