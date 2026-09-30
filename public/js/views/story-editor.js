// Story editor dialog: Connextra parts, size, status, criteria, open questions, notes.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";

const STATUSES = ["idea", "needs_clarification", "reviewed", "ready"];
const SIZES = ["", "S", "M", "L"];

export function openStoryEditor(state, story, reload) {
  const { project, roles, stories } = state;
  const isNew = !story;
  const phraseFor = (name) => stories.find((s) => s.role_name === name)?.role_phrase ?? "";

  const field = (tag, attrs, value) => {
    const el = h(tag, attrs);
    el.value = value ?? "";
    return el;
  };
  const roleName = field("input", { id: "st-role", list: "st-roles", maxlength: 60, required: true, autocomplete: "off" },
    story?.role_name ?? roles[0]?.name);
  const rolePhrase = field("input", { id: "st-phrase", maxlength: 80, required: true, placeholder: t("editor.phrase_hint") },
    story?.role_phrase ?? phraseFor(roleName.value));
  const action = field("textarea", { id: "st-action", rows: 2, maxlength: 300, required: true }, story?.action);
  const benefit = field("textarea", { id: "st-benefit", rows: 2, maxlength: 300, required: true }, story?.benefit);
  const size = field("select", { id: "st-size" }, story?.size ?? "");
  size.append(...SIZES.map((v) => h("option", { value: v }, v || t("editor.size_none"))));
  size.value = story?.size ?? "";
  const status = h("select", { id: "st-status" }, STATUSES.map((v) => h("option", { value: v }, t(`status.${v}`))));
  status.value = story?.status ?? "idea";
  const notes = field("textarea", { id: "st-notes", rows: 2, maxlength: 2000 }, story?.notes);
  const criteria = lineList(story?.criteria.map((c) => c.text) ?? [], t("editor.add_criterion"), t("editor.criterion_hint"));
  const questions = lineList(story?.open_questions ?? [], t("editor.add_question"), t("editor.question_hint"));
  const preview = h("p", { class: "title-preview" });
  const errors = h("div", { class: "form-status" });

  const updatePreview = () => {
    const phrase = rolePhrase.value.trim();
    preview.textContent = t("story.title", {
      role: phrase ? phrase.charAt(0).toUpperCase() + phrase.slice(1) : "…",
      action: action.value.trim() || "…",
      benefit: benefit.value.trim().replace(/\.$/, "") || "…",
    });
  };
  // Suggest the title phrase from an existing story with that role, until the user writes their own.
  let phraseTyped = Boolean(story);
  rolePhrase.addEventListener("input", () => { phraseTyped = true; });
  roleName.addEventListener("input", () => {
    if (!phraseTyped) rolePhrase.value = phraseFor(roleName.value);
    updatePreview();
  });
  [rolePhrase, action, benefit].forEach((el) => el.addEventListener("input", updatePreview));
  updatePreview();

  const dialog = h("dialog", { class: "editor", "aria-labelledby": "st-heading" });
  const close = () => { dialog.close(); dialog.remove(); };

  async function save(event) {
    event.preventDefault();
    const data = {
      role_name: roleName.value, role_phrase: rolePhrase.value, action: action.value, benefit: benefit.value,
      status: status.value, criteria: criteria.values(), open_questions: questions.values(), notes: notes.value,
    };
    if (size.value) data.size = size.value; else if (!isNew) data.clear_size = true;
    try {
      if (isNew) await api.createStory(project.id, data);
      else await api.patchStory(project.id, story.id, data);
      close();
      await reload();
    } catch (error) {
      mount(errors, notice(errorText(error), "error"));
    }
  }

  async function remove() {
    if (!confirm(t("editor.confirm_delete", { key: story.key }))) return;
    try {
      await api.deleteStory(project.id, story.id);
      close();
      await reload();
    } catch (error) {
      mount(errors, notice(errorText(error), "error"));
    }
  }

  const label = (id, text) => h("label", { for: id }, text);
  mount(dialog, h("form", { method: "dialog", onsubmit: save },
    h("h2", { id: "st-heading" }, isNew ? t("editor.new") : t("editor.edit", { key: story.key })),
    h("datalist", { id: "st-roles" }, roles.map((r) => h("option", { value: r.name }))),
    h("div", { class: "grid-2" },
      h("div", {}, label("st-role", t("editor.role")), roleName),
      h("div", {}, label("st-phrase", t("editor.phrase")), rolePhrase)),
    label("st-action", t("editor.action")), action,
    label("st-benefit", t("editor.benefit")), benefit,
    h("div", { class: "preview-box" }, h("span", { class: "hint" }, t("editor.preview")), preview),
    h("div", { class: "grid-2" },
      h("div", {}, label("st-size", t("editor.size")), size),
      h("div", {}, label("st-status", t("editor.status")), status)),
    h("fieldset", {}, h("legend", {}, t("editor.criteria")), criteria.element),
    h("fieldset", {}, h("legend", {}, t("editor.questions")), questions.element),
    label("st-notes", t("editor.notes")), notes,
    errors,
    h("div", { class: "dialog-actions" },
      isNew ? null : h("button", { type: "button", class: "danger", onclick: remove }, t("editor.delete")),
      h("button", { type: "button", onclick: close }, t("editor.cancel")),
      h("button", { type: "submit", class: "primary" }, t("editor.save")))));

  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dialog);
  dialog.showModal();
  (isNew ? action : roleName).focus();
}

// An editable list of one-line texts (criteria, open questions).
function lineList(initial, addLabel, placeholder) {
  const list = h("ol", { class: "line-list" });
  const addLine = (value = "", focus = false) => {
    const input = h("input", { type: "text", maxlength: 500, placeholder });
    input.value = value;
    const item = h("li", {}, input,
      h("button", { type: "button", class: "icon", "aria-label": t("editor.remove_line"),
        onclick: () => item.remove() }, "×"));
    list.append(item);
    if (focus) input.focus();
  };
  initial.forEach((value) => addLine(value));
  const element = h("div", {}, list,
    h("button", { type: "button", class: "small", onclick: () => addLine("", true) }, `+ ${addLabel}`));
  return { element, values: () => [...list.querySelectorAll("input")].map((i) => i.value.trim()).filter(Boolean) };
}
