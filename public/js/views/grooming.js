// Grooming dialogs: split a story into parts, merge two overlapping stories.
// Both preview the result on the server (dry run) before anything changes.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";

function dialogShell(title) {
  const dialog = h("dialog", { class: "editor grooming", "aria-label": title });
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dialog);
  return { dialog, close };
}

function input(value, attrs = {}) {
  const el = h("input", { type: "text", maxlength: 300, ...attrs });
  el.value = value ?? "";
  return el;
}

function storyPreview(story, extra = null) {
  return h("div", { class: "preview-story" },
    h("div", { class: "story-meta" }, h("span", { class: "story-key" }, story.key)),
    h("p", { class: "title-preview" }, story.title),
    story.criteria.length ? h("ol", {}, story.criteria.map((c) => h("li", {}, c.text))) : h("p", { class: "hint" }, t("grooming.no_criteria")),
    extra);
}

// --- split ---------------------------------------------------------------

export function openSplitDialog(state, story, reload) {
  const { dialog, close } = dialogShell(t("grooming.split_title", { key: story.key }));
  const partsBox = h("div", { class: "split-parts" });
  const assignBox = h("div", { class: "split-assign" });
  const previewBox = h("div", { class: "grooming-preview" });
  const status = h("div", { class: "form-status" });
  const confirmButton = h("button", { type: "button", class: "primary", disabled: true }, t("grooming.split_confirm"));

  const parts = [
    { role_phrase: story.role_phrase, action: story.action, benefit: story.benefit },
    { role_phrase: story.role_phrase, action: "", benefit: story.benefit },
  ];
  const assignment = new Map(story.criteria.map((c) => [c.id, 0])); // criterion id -> part index, -1 = drop

  const payload = (dryRun) => ({
    dry_run: dryRun,
    parts: parts.map((p, i) => ({
      role_phrase: p.role_phrase.trim(), action: p.action.trim(), benefit: p.benefit.trim(),
      criterion_ids: story.criteria.filter((c) => assignment.get(c.id) === i).map((c) => c.id),
      new_criteria: (p.newCriteria ?? "").split("\n").map((l) => l.trim()).filter(Boolean),
    })),
  });

  const stale = () => { confirmButton.disabled = true; mount(previewBox); };

  function drawParts() {
    mount(partsBox, parts.map((part, i) => {
      const fields = ["role_phrase", "action", "benefit"].map((name) => {
        const el = input(part[name], { "aria-label": `${t("grooming.part", { n: i + 1 })}: ${t(`editor.${name === "role_phrase" ? "phrase" : name}`)}`,
          placeholder: t(`editor.${name === "role_phrase" ? "phrase" : name}`) });
        el.addEventListener("input", () => { part[name] = el.value; stale(); });
        return el;
      });
      const extra = h("textarea", { rows: 2, placeholder: t("grooming.new_criteria_hint") });
      extra.value = part.newCriteria ?? "";
      extra.addEventListener("input", () => { part.newCriteria = extra.value; stale(); });
      return h("fieldset", {}, h("legend", {}, t("grooming.part", { n: i + 1 }), i === 0 ? h("span", { class: "hint" }, ` (${story.key})`) : null),
        h("div", { class: "connextra-row" }, fields[0], h("span", {}, t("grooming.want")), fields[1], h("span", {}, t("grooming.so_that")), fields[2]),
        extra,
        i >= 2 ? h("button", { type: "button", class: "small", onclick: () => {
          parts.splice(i, 1);
          assignment.forEach((v, k) => { if (v >= i) assignment.set(k, v === i ? 0 : v - 1); });
          drawParts(); drawAssign(); stale();
        } }, t("grooming.remove_part")) : null);
    }),
    parts.length < 5 ? h("button", { type: "button", class: "small", onclick: () => {
      parts.push({ role_phrase: story.role_phrase, action: "", benefit: story.benefit });
      drawParts(); drawAssign(); stale();
    } }, `+ ${t("grooming.add_part")}`) : null);
  }

  function drawAssign() {
    mount(assignBox, story.criteria.length ? h("table", { class: "assign" },
      h("tbody", {}, story.criteria.map((c) => {
        const select = h("select", { "aria-label": c.text },
          parts.map((_, i) => h("option", { value: i }, t("grooming.part", { n: i + 1 }))),
          h("option", { value: -1 }, t("grooming.drop")));
        select.value = String(assignment.get(c.id));
        select.addEventListener("change", () => { assignment.set(c.id, Number(select.value)); stale(); });
        return h("tr", {}, h("td", {}, c.text), h("td", {}, select));
      }))) : h("p", { class: "hint" }, t("grooming.no_criteria")));
  }

  async function run(dryRun) {
    mount(status);
    try {
      const result = await api.splitStory(state.project.id, story.id, payload(dryRun));
      if (!dryRun) { close(); await reload(); return; }
      mount(previewBox, h("h3", {}, t("grooming.preview")), result.map((s) => storyPreview(s)));
      confirmButton.disabled = false;
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
    }
  }
  confirmButton.addEventListener("click", () => run(false));

  drawParts();
  drawAssign();
  mount(dialog,
    h("h2", {}, t("grooming.split_title", { key: story.key })),
    h("p", { class: "hint" }, story.title),
    partsBox,
    h("h3", {}, t("grooming.assign")), assignBox,
    previewBox, status,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", onclick: close }, t("editor.cancel")),
      h("button", { type: "button", onclick: () => run(true) }, t("grooming.preview")),
      confirmButton));
  dialog.showModal();
}

// --- merge ---------------------------------------------------------------

export function openMergeDialog(state, story, reload) {
  const { dialog, close } = dialogShell(t("grooming.merge_title", { key: story.key }));
  const others = state.stories.filter((s) => s.id !== story.id);
  const other = h("select", { "aria-label": t("grooming.merge_with") }, others.map((s) => h("option", { value: s.id }, `${s.key}: ${s.title}`)));
  const keepFirst = h("input", { type: "radio", name: "keep", checked: true });
  const keepOther = h("input", { type: "radio", name: "keep" });
  const previewBox = h("div", { class: "grooming-preview" });
  const status = h("div", { class: "form-status" });
  const confirmButton = h("button", { type: "button", class: "primary", disabled: true }, t("grooming.merge_confirm"));
  const removeInstead = h("button", { type: "button", class: "danger", disabled: true });

  const pair = () => {
    const second = others.find((s) => s.id === Number(other.value));
    return keepFirst.checked ? { keep: story, remove: second } : { keep: second, remove: story };
  };

  async function preview() {
    mount(status);
    const { keep, remove } = pair();
    removeInstead.textContent = t("grooming.remove_instead", { key: remove.key });
    try {
      const result = await api.mergeStories(state.project.id, { keep_id: keep.id, remove_id: remove.id, dry_run: true });
      mount(previewBox, h("h3", {}, t("grooming.merged_result")),
        storyPreview(result.story, [
          result.dropped_duplicates.length ? h("p", { class: "hint" }, t("grooming.duplicates"),
            h("ul", { class: "dropped" }, result.dropped_duplicates.map((d) => h("li", {}, d)))) : null,
          result.story.open_questions.length ? h("p", { class: "hint" }, `${t("editor.questions")}: ${result.story.open_questions.join("; ")}`) : null,
          h("p", { class: "hint" }, t("grooming.removed", { key: result.removed_key })),
        ]));
      confirmButton.disabled = false;
      removeInstead.disabled = false;
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
    }
  }

  confirmButton.addEventListener("click", async () => {
    const { keep, remove } = pair();
    try {
      await api.mergeStories(state.project.id, { keep_id: keep.id, remove_id: remove.id });
      close(); await reload();
    } catch (error) { mount(status, notice(errorText(error), "error")); }
  });
  removeInstead.addEventListener("click", async () => {
    const { remove } = pair();
    if (!confirm(t("editor.confirm_delete", { key: remove.key }))) return;
    try {
      await api.deleteStory(state.project.id, remove.id);
      close(); await reload();
    } catch (error) { mount(status, notice(errorText(error), "error")); }
  });
  [other, keepFirst, keepOther].forEach((el) => el.addEventListener("change", preview));

  mount(dialog,
    h("h2", {}, t("grooming.merge_title", { key: story.key })),
    others.length ? [
      h("label", {}, t("grooming.merge_with"), other),
      h("div", { class: "keep-choice" }, h("span", {}, t("grooming.keep")),
        h("label", { class: "check" }, keepFirst, story.key),
        h("label", { class: "check" }, keepOther, t("grooming.keep_other"))),
      previewBox, status,
    ] : h("p", { class: "hint" }, t("grooming.no_others")),
    h("div", { class: "dialog-actions" },
      removeInstead,
      h("button", { type: "button", onclick: close }, t("editor.cancel")),
      confirmButton));
  dialog.showModal();
  if (others.length) preview();
}
