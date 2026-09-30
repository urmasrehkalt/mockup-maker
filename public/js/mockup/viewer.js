// Mockup viewer: a large preview with a desktop / mobile toggle.

import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { renderTree } from "./render.js";

export function openMockupViewer(mockup) {
  const stage = h("div", { class: "wf-stage" });
  let viewport = "desktop";
  const toggles = ["desktop", "mobile"].map((v) => h("button", {
    type: "button", class: "small", "aria-pressed": String(v === viewport),
    onclick: () => { viewport = v; draw(); },
  }, t(`mockup.${v}`)));

  const draw = () => {
    toggles.forEach((b, i) => b.setAttribute("aria-pressed", String(["desktop", "mobile"][i] === viewport)));
    mount(stage, renderTree(mockup.tree, { viewport }));
  };

  const dialog = h("dialog", { class: "editor viewer", "aria-label": mockup.title });
  const close = () => { dialog.close(); dialog.remove(); };
  mount(dialog,
    h("div", { class: "viewer-head" },
      h("h2", {}, mockup.title, h("span", { class: "muted" }, ` · v${mockup.version}`)),
      h("div", { class: "segmented" }, toggles),
      h("button", { type: "button", class: "small", onclick: close }, t("mockup.close"))),
    stage);
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dialog);
  draw();
  dialog.showModal();
}
