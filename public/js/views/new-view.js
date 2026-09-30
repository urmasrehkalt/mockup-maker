// "New view" dialog: describe a view in words (optionally from a template); the AI answers
// in the chat with the story, its criteria and the mockup, saved only when the user adds it.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { openStoryEditor } from "./story-editor.js";

/**
 * @param state   project state
 * @param send    (input) => void, posts a conversation turn
 * @param reload  async () => state
 */
export async function openNewViewDialog(state, send, reload) {
  const dialog = h("dialog", { class: "editor new-view", "aria-labelledby": "nv-title" });
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dialog);

  const [ai, templates] = await Promise.all([
    api.aiStatus().catch(() => ({ enabled: false })),
    api.templates(state.project.language).catch(() => []),
  ]);
  const manual = h("button", { type: "button", onclick: () => { close(); openStoryEditor(state, null, reload); } },
    t("newview.manual"));

  if (!ai.enabled) {
    mount(dialog, h("h2", { id: "nv-title" }, t("newview.title")),
      h("p", { class: "notice" }, t("newview.ai_off")),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", onclick: close }, t("editor.cancel")), manual));
    dialog.showModal();
    return;
  }

  const text = h("textarea", { id: "nv-text", rows: 4, maxlength: 1000, required: true, placeholder: t("newview.hint") });
  const template = h("select", { id: "nv-template" },
    h("option", { value: "" }, t("newview.template_ai")),
    templates.map((tpl) => h("option", { value: tpl.key }, tpl.name)));
  const submit = (event) => {
    event.preventDefault();
    if (!text.value.trim()) { text.focus(); return; }
    close();
    send({ kind: "new_view", text: text.value.trim(), template: template.value || null });
  };

  mount(dialog, h("form", { onsubmit: submit },
    h("h2", { id: "nv-title" }, t("newview.title")),
    h("p", { class: "hint" }, t("newview.explain")),
    h("label", { for: "nv-text" }, t("newview.describe")), text,
    h("label", { for: "nv-template" }, t("newview.template")), template,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "quiet-button", onclick: () => { close(); openStoryEditor(state, null, reload); } }, t("newview.manual")),
      h("button", { type: "button", onclick: close }, t("editor.cancel")),
      h("button", { type: "submit", class: "primary" }, t("newview.create")))));
  dialog.showModal();
  text.focus();
}
