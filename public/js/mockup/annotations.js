// Annotation layer: freehand marks (box, arrow, pen, note) on top of a mockup.
//
// The mockup is laid out on a fixed 1024-px "artboard" (the PNG export's width)
// and scaled to fit; an SVG layer on top holds the marks. Each mark is stored
// relative to the component under its first point (its anchor), so it stays with
// that component in the PNG too, whose layout differs slightly.
// Marks are SVG elements and note text is set with textContent: nothing is HTML.

import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { renderTree } from "./render.js";

const SVG = "http://www.w3.org/2000/svg";
const WIDTH = 1024;
const COLORS = { red: "#e03131", blue: "#1c7ed6", green: "#2f9e44" };
const TOOLS = ["rect", "arrow", "pen", "note", "eraser"];

function svg(tag, attrs = {}) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

function wrapText(text, perLine = 28) {
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    if ((line + " " + word).trim().length > perLine && line) { lines.push(line); line = word; }
    else line = (line + " " + word).trim();
  }
  if (line) lines.push(line);
  return lines;
}

/**
 * @param tree         the mockup's component tree
 * @param annotations  the marks to show (copied; the original is not changed)
 * @param options      { editable, onSave(marks), onCancel }
 */
export function createArtboard(tree, annotations = [], { editable = false, onSave = null, onCancel = null } = {}) {
  let marks = structuredClone(annotations);
  let tool = "rect";
  let color = "red";
  let draft = null;

  const view = renderTree(tree);
  view.classList.add("wf-fixed");
  const layer = svg("svg", { class: "mark-layer", role: "img", "aria-label": t("marks.layer") });
  const scaler = h("div", { class: "artboard-scale" }, view, layer);
  const board = h("div", { class: `artboard ${editable ? "editable" : ""}` }, scaler);

  // Component boxes in artboard coordinates, measured from the rendered wireframe.
  const scale = () => (scaler.getBoundingClientRect().width || WIDTH) / WIDTH;
  function boxes() {
    const origin = view.getBoundingClientRect();
    const k = scale();
    const out = {};
    view.querySelectorAll("[data-component-id]").forEach((el) => {
      const r = el.getBoundingClientRect();
      out[el.dataset.componentId] = { x: (r.left - origin.left) / k, y: (r.top - origin.top) / k, w: r.width / k, h: r.height / k };
    });
    return out;
  }
  const absolute = (mark, known) => {
    const o = known[mark.anchor] ?? { x: 0, y: 0 };
    return mark.points.map(([x, y]) => [o.x + x, o.y + y]);
  };
  function anchorFor(point, known) {
    let best = null;
    for (const [id, b] of Object.entries(known)) {
      const inside = point[0] >= b.x && point[0] <= b.x + b.w && point[1] >= b.y && point[1] <= b.y + b.h;
      if (inside && (!best || b.w * b.h < best.area)) best = { id, area: b.w * b.h };
    }
    return best?.id ?? null;
  }

  function markElement(mark, known) {
    const pts = absolute(mark, known);
    const stroke = COLORS[mark.color];
    const common = { stroke, "stroke-width": 3, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" };
    let el;
    if (mark.tool === "rect") {
      const [[x1, y1], [x2, y2]] = pts;
      el = svg("rect", { ...common, x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) });
    } else if (mark.tool === "arrow") {
      const [[x1, y1], [x2, y2]] = pts;
      const a = Math.atan2(y2 - y1, x2 - x1);
      const head = [-0.5, 0.5].map((s) => `${x2 - 14 * Math.cos(a + s)},${y2 - 14 * Math.sin(a + s)}`);
      el = svg("g");
      el.append(svg("line", { ...common, x1, y1, x2, y2 }), svg("polyline", { ...common, points: `${head[0]} ${x2},${y2} ${head[1]}` }));
    } else if (mark.tool === "pen") {
      el = svg("polyline", { ...common, points: pts.map((p) => p.join(",")).join(" ") });
    } else {
      const [x, y] = pts[0];
      const lines = wrapText(mark.text ?? "");
      el = svg("g");
      el.append(svg("rect", { x, y, width: 216, height: 10 + 18 * lines.length, fill: "#fff3bf", stroke, "stroke-width": 2 }));
      const text = svg("text", { x: x + 8, y: y + 18, "font-size": 13, fill: "#2b2f33", "font-family": "system-ui, sans-serif" });
      lines.forEach((line, i) => {
        const span = svg("tspan", { x: x + 8, dy: i ? 18 : 0 });
        span.textContent = line;
        text.append(span);
      });
      el.append(text);
    }
    el.dataset.markId = mark.id;
    el.classList.add("mark");
    return el;
  }

  function draw() {
    const height = Math.max(view.offsetHeight, 200);
    layer.setAttribute("viewBox", `0 0 ${WIDTH} ${height}`);
    layer.setAttribute("width", WIDTH);
    layer.setAttribute("height", height);
    const known = boxes();
    layer.replaceChildren(...marks.map((m) => markElement(m, known)), ...(draft ? [markElement(draft.mark, {})] : []));
  }

  // Scaled with a transform (not CSS zoom): measured element rects then come back
  // in screen pixels consistently, which the anchor maths relies on.
  function fit() {
    const k = Math.min(1, (board.clientWidth || WIDTH) / WIDTH);
    scaler.style.transform = `scale(${k})`;
    board.style.height = `${Math.max(view.offsetHeight, 200) * k}px`;
    draw();
  }
  // Keep the observer referenced from the board: an unreferenced ResizeObserver can
  // be garbage-collected, and then the artboard is never scaled or measured.
  board.resizeObserver = new ResizeObserver(fit);
  board.resizeObserver.observe(board);
  requestAnimationFrame(fit);

  if (!editable) return { element: board, redraw: fit };

  // --- drawing ---------------------------------------------------------------
  const noteText = h("input", { type: "text", maxlength: 200, placeholder: t("marks.note_hint"), "aria-label": t("marks.note_hint"), hidden: true });
  const toolButtons = TOOLS.map((name) => h("button", { type: "button", class: "small", "aria-pressed": String(name === tool),
    onclick: () => { tool = name; toolButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(TOOLS[i] === tool))); noteText.hidden = tool !== "note"; board.dataset.tool = tool; } },
  t(`marks.${name}`)));
  const colorButtons = Object.entries(COLORS).map(([name, value]) => h("button", { type: "button", class: "swatch",
    style: `--swatch: ${value}`, "aria-label": t(`marks.color_${name}`), "aria-pressed": String(name === color),
    onclick: () => { color = name; colorButtons.forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("aria-label") === t(`marks.color_${color}`)))); } }));
  board.dataset.tool = tool;

  const toPoint = (e) => {
    const r = layer.getBoundingClientRect();
    const k = r.width / WIDTH;
    return [Math.round((e.clientX - r.left) / k), Math.round((e.clientY - r.top) / k)];
  };
  const id = () => `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

  layer.addEventListener("pointerdown", (e) => {
    const point = toPoint(e);
    if (tool === "eraser") {
      const target = e.target.closest("[data-mark-id]");
      if (target) { marks = marks.filter((m) => m.id !== target.dataset.markId); draw(); }
      return;
    }
    if (tool === "note") {
      const text = noteText.value.trim();
      if (!text) { noteText.focus(); return; }
      const known = boxes();
      const anchor = anchorFor(point, known);
      const o = known[anchor] ?? { x: 0, y: 0 };
      marks.push({ id: id(), tool: "note", anchor, points: [[point[0] - o.x, point[1] - o.y]], text, color });
      noteText.value = "";
      draw();
      return;
    }
    layer.setPointerCapture(e.pointerId);
    draft = { start: point, mark: { id: id(), tool, anchor: null, points: [point, point], color } };
  });
  layer.addEventListener("pointermove", (e) => {
    if (!draft) return;
    const point = toPoint(e);
    if (tool === "pen") {
      const last = draft.mark.points.at(-1);
      if (Math.hypot(point[0] - last[0], point[1] - last[1]) >= 3 && draft.mark.points.length < 500) draft.mark.points.push(point);
    } else {
      draft.mark.points[1] = point;
    }
    draw();
  });
  layer.addEventListener("pointerup", () => {
    if (!draft) return;
    const mark = draft.mark;
    draft = null;
    const [a, b] = [mark.points[0], mark.points.at(-1)];
    if (mark.tool === "pen" ? mark.points.length < 2 : Math.hypot(b[0] - a[0], b[1] - a[1]) < 6) { draw(); return; }
    const known = boxes();
    mark.anchor = anchorFor(mark.points[0], known);
    const o = known[mark.anchor] ?? { x: 0, y: 0 };
    mark.points = mark.points.map(([x, y]) => [x - o.x, y - o.y]);
    marks.push(mark);
    draw();
  });

  const toolbar = h("div", { class: "mark-toolbar" },
    h("div", { class: "segmented" }, toolButtons),
    h("div", { class: "swatches" }, colorButtons),
    noteText,
    h("button", { type: "button", class: "small", onclick: () => { marks = []; draw(); } }, t("marks.clear")),
    h("span", { class: "spacer" }),
    h("button", { type: "button", class: "small", onclick: () => onCancel?.() }, t("editor.cancel")),
    h("button", { type: "button", class: "small primary", onclick: () => onSave?.(marks) }, t("marks.save")));
  return { element: h("div", { class: "annotating" }, toolbar, board), redraw: fit };
}
