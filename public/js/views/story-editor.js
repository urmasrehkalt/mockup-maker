// Story editor dialog: Connextra parts, size, status, criteria, open questions, notes.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { contentText, storyTitle, t } from "../i18n.js";
import { errorText, issueList, notice, readinessList } from "../ui.js";
import { storyMockups } from "../mockup/story-mockups.js";
import { openMergeDialog, openSplitDialog } from "./grooming.js";

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
  const rolePhrase = field("input", { id: "st-phrase", maxlength: 80, required: true, placeholder: contentText(project.language, "phraseHint") },
    story?.role_phrase ?? phraseFor(roleName.value));
  const action = field("textarea", { id: "st-action", rows: 2, maxlength: 300, required: true }, story?.action);
  const benefit = field("textarea", { id: "st-benefit", rows: 2, maxlength: 300, required: true }, story?.benefit);
  const size = field("select", { id: "st-size" }, story?.size ?? "");
  size.append(...SIZES.map((v) => h("option", { value: v }, v || t("editor.size_none"))));
  size.value = story?.size ?? "";
  const status = h("select", { id: "st-status" }, STATUSES.map((v) => h("option", { value: v }, t(`status.${v}`))));
  status.value = story?.status ?? "idea";
  const notes = field("textarea", { id: "st-notes", rows: 2, maxlength: 2000 }, story?.notes);
  const needsView = h("input", { type: "checkbox", id: "st-view", checked: story?.needs_view ?? true });
  const criteria = lineList(story?.criteria.map((c) => c.text) ?? [], t("editor.add_criterion"), t("editor.criterion_hint"), true);
  const questions = lineList(story?.open_questions ?? [], t("editor.add_question"), t("editor.question_hint"));
  const preview = h("p", { class: "title-preview" });
  status.addEventListener("change", () => {
    if (status.value === "needs_clarification" && !questions.values().length) questions.addLine("", true);
  });
  const errors = h("div", { class: "form-status" });

  const updatePreview = () => {
    const phrase = rolePhrase.value.trim();
    preview.textContent = storyTitle({
      role_phrase: phrase || "…", action: action.value.trim() || "…", benefit: benefit.value.trim() || "…",
    }, project.language);
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
      needs_view: needsView.checked,
    };
    if (size.value) data.size = size.value; else if (!isNew) data.clear_size = true;
    try {
      if (isNew) await api.createStory(project.id, data);
      else await api.patchStory(project.id, story.id, data);
      close();
      await reload();
    } catch (error) {
      mount(errors, notice(errorText(error), "error"),
        error.code === "not_ready" ? readinessList({ needs_view: needsView.checked }, error.details.missing) : null);
      errors.scrollIntoView({ block: "nearest" });
    }
  }

  async function startHere() {
    try {
      await api.patchProject(project.id, { current_story_id: story.id });
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
      h("div", {}, label("st-phrase", contentText(project.language, "phrase")), rolePhrase)),
    label("st-action", contentText(project.language, "action")), action,
    label("st-benefit", contentText(project.language, "benefit")), benefit,
    h("div", { class: "preview-box" }, h("span", { class: "hint" }, t("editor.preview")), preview),
    h("div", { class: "grid-2" },
      h("div", {}, label("st-size", t("editor.size")), size),
      h("div", {}, label("st-status", t("editor.status")), status)),
    h("label", { class: "check", for: "st-view" }, needsView, t("editor.needs_view")),
    story ? h("details", { class: "ready-box", open: story.readiness.length > 0 },
      h("summary", {}, story.readiness.length ? t("ready.summary_missing", { count: story.readiness.length }) : t("ready.summary_ok")),
      readinessList(story)) : null,
    h("fieldset", {}, h("legend", {}, t("editor.criteria")), criteria.element),
    h("fieldset", {}, h("legend", {}, t("editor.questions")), questions.element),
    label("st-notes", t("editor.notes")), notes,
    storyMockups(state, story, reload),
    errors,
    isNew ? null : h("div", { class: "grooming-actions" },
      h("span", { class: "hint" }, t("grooming.label")),
      h("button", { type: "button", class: "small", disabled: project.current_story_id === story.id,
        onclick: startHere }, `▶ ${t("grooming.start_here")}`),
      h("button", { type: "button", class: "small", onclick: () => { close(); openSplitDialog(state, story, reload); } },
        t("grooming.split")),
      h("button", { type: "button", class: "small", disabled: stories.length < 2,
        onclick: () => { close(); openMergeDialog(state, story, reload); } }, t("grooming.merge"))),
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
// With `checked`, each line shows its testability warnings as the user types.
function lineList(initial, addLabel, placeholder, checked = false) {
  const list = h("ol", { class: "line-list" });
  const addLine = (value = "", focus = false) => {
    const input = h("input", { type: "text", maxlength: 500, placeholder });
    input.value = value;
    const warnings = h("div", { class: "line-issues", "aria-live": "polite" });
    const item = h("li", {}, input,
      h("button", { type: "button", class: "icon", "aria-label": t("editor.remove_line"),
        onclick: () => item.remove() }, "×"), checked ? warnings : null);
    if (checked) {
      let timer;
      const recheck = async () => {
        const text = input.value.trim();
        const issues = text ? await api.checkCriteria([text]).then((r) => r[0]).catch(() => []) : [];
        mount(warnings, issueList(issues));
      };
      input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(recheck, 300); });
      if (value) recheck();
    }
    list.append(item);
    if (focus) input.focus();
  };
  initial.forEach((value) => addLine(value));
  const element = h("div", {}, list,
    h("button", { type: "button", class: "small", onclick: () => addLine("", true) }, `+ ${addLabel}`));
  return { element, addLine, values: () => [...list.querySelectorAll("input")].map((i) => i.value.trim()).filter(Boolean) };
}
