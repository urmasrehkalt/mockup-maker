// Backlog review card: one block per finding with its problem, reason and a preview
// of the proposal; Apply, Edit and Ignore decide each finding on its own.

import { h, mount } from "../dom.js";
import { t } from "../i18n.js";

const title = (w) => {
  const phrase = w.role_phrase.charAt(0).toUpperCase() + w.role_phrase.slice(1);
  return t("story.title", { role: phrase, action: w.action, benefit: w.benefit.replace(/\.$/, "") });
};
const PROPOSAL = { too_large: "split", overlap: "merge", untestable_criteria: "criteria",
  missing_criteria: "criteria", no_mockup: "mockup", not_connextra: "wording" };

export function reviewCard(message, send, templates) {
  const findings = message.content.review.findings;
  if (!findings.length) return h("div", { class: "card-block answered" }, h("p", { class: "muted" }, t("review.none")));
  return h("div", { class: "card-block review" },
    h("div", { class: "card-title" }, t("review.title", { count: findings.length })),
    h("ol", { class: "findings" }, findings.map((f, index) => findingItem(f, index, message, send, templates))));
}

function findingItem(f, index, message, send, templates) {
  const item = h("li", { class: `finding ${f.status}` });
  const decide = (data) => send({ kind: "finding", message_id: message.id, index, data });
  const kind = PROPOSAL[f.kind];

  const head = () => [
    h("div", { class: "finding-head" },
      h("span", { class: `kind kind-${f.kind}` }, t(`review.kind.${f.kind}`)),
      h("span", { class: "story-key" }, f.story_keys.join(" + ")),
      f.status !== "pending" ? h("span", { class: `decided ${f.status}` }, t(`review.${f.status}`)) : null),
    h("p", { class: "finding-problem" }, f.problem),
    h("p", { class: "hint" }, h("strong", {}, t("chat.priority_why")), " ", f.reason),
  ];

  const show = () => {
    mount(item, head(), h("div", { class: "finding-proposal" }, preview(f, templates)),
      f.status === "pending" ? h("div", { class: "card-actions" },
        h("button", { type: "button", class: "quiet-button", onclick: () => decide({ decision: "ignore" }) }, t("review.ignore")),
        h("button", { type: "button", onclick: edit }, `✎ ${t("chat.edit")}`),
        h("button", { type: "button", class: "primary", onclick: () => decide({ decision: "apply" }) }, t("chat.apply"))) : null);
  };

  const edit = () => {
    const form = editor(f, kind, templates);
    mount(item, head(), h("div", { class: "finding-proposal" }, form.element),
      h("div", { class: "card-actions" },
        h("button", { type: "button", onclick: show }, t("editor.cancel")),
        h("button", { type: "button", class: "primary", onclick: () => decide({ decision: "apply", [kind]: form.value() }) },
          t("chat.apply_edited"))));
  };

  show();
  return item;
}

function list(items, cls = "") {
  return h("ul", { class: `proposal-list ${cls}` }, items.map((x) => h("li", {}, x)));
}

function preview(f, templates) {
  const before = f.before[0];
  if (f.split) {
    return h("div", { class: "split-preview" }, f.split.parts.map((p, i) => h("div", { class: "preview-story" },
      h("div", { class: "hint" }, i === 0 ? t("review.part_keeps", { key: before.key }) : t("review.part_new")),
      h("p", { class: "title-preview" }, title(p)),
      list([...p.criteria.map((c) => before.criteria[c]), ...p.new_criteria.map((c) => `+ ${c}`)]))));
  }
  if (f.merge) {
    const keep = f.before.find((b) => b.key === f.merge.keep_key);
    return h("div", { class: "preview-story" },
      h("p", { class: "title-preview" }, f.merge.wording ? title(f.merge.wording) : keep.title),
      list(f.merge.criteria),
      f.dropped_duplicates?.length ? h("p", { class: "hint" }, t("grooming.duplicates"), list(f.dropped_duplicates, "dropped")) : null,
      f.dropped_other?.length ? h("p", { class: "hint" }, t("review.dropped_other"), list(f.dropped_other, "dropped")) : null,
      h("p", { class: "hint" }, t("grooming.removed", { key: f.merge.remove_key })));
  }
  if (f.criteria) {
    const now = new Set(f.criteria.criteria);
    return h("div", {},
      list([...f.criteria.criteria.map((c) => (before.criteria.includes(c) ? c : `+ ${c}`))]),
      before.criteria.filter((c) => !now.has(c)).length
        ? list(before.criteria.filter((c) => !now.has(c)).map((c) => `− ${c}`), "dropped") : null);
  }
  if (f.mockup) {
    const tpl = templates.find((x) => x.key === f.mockup.template);
    return h("p", {}, t("review.mockup_from", { template: tpl?.name ?? f.mockup.template, title: f.mockup.title }));
  }
  if (f.wording) {
    return h("div", {}, h("p", { class: "removed-title" }, before.title), h("p", { class: "title-preview" }, title(f.wording)));
  }
  return null;
}

// An editable copy of the proposal; value() returns it in the proposal's shape.
function editor(f, kind, templates) {
  const text = (value, label) => {
    const el = h("input", { type: "text", maxlength: 300, "aria-label": label });
    el.value = value ?? "";
    return el;
  };
  const lines = (values) => {
    const el = h("textarea", { rows: Math.max(3, values.length + 1), "aria-label": t("editor.criteria") });
    el.value = values.join("\n");
    return el;
  };
  const read = (el) => el.value.split("\n").map((l) => l.trim()).filter(Boolean);
  const wordingFields = (w) => {
    const fields = { role_phrase: text(w.role_phrase, t("editor.phrase")), action: text(w.action, t("editor.action")),
      benefit: text(w.benefit, t("editor.benefit")) };
    return { element: h("div", { class: "connextra-row" }, fields.role_phrase, h("span", {}, t("grooming.want")),
      fields.action, h("span", {}, t("grooming.so_that")), fields.benefit),
    value: () => Object.fromEntries(Object.entries(fields).map(([k, el]) => [k, el.value.trim()])) };
  };

  if (kind === "split") {
    const parts = f.split.parts.map((p) => ({ part: p, fields: wordingFields(p) }));
    return { element: h("div", {}, parts.map((x, i) => h("fieldset", {}, h("legend", {}, t("grooming.part", { n: i + 1 })), x.fields.element))),
      value: () => ({ parts: parts.map((x) => ({ ...x.part, ...x.fields.value() })) }) };
  }
  if (kind === "merge") {
    const criteria = lines(f.merge.criteria);
    return { element: h("div", {}, h("p", { class: "hint" }, t("chat.one_per_line")), criteria),
      value: () => ({ ...f.merge, criteria: read(criteria) }) };
  }
  if (kind === "criteria") {
    const criteria = lines(f.criteria.criteria);
    return { element: h("div", {}, h("p", { class: "hint" }, t("chat.one_per_line")), criteria),
      value: () => ({ criteria: read(criteria) }) };
  }
  if (kind === "mockup") {
    const select = h("select", { "aria-label": t("mockup.template") }, templates.map((tpl) => h("option", { value: tpl.key }, tpl.name)));
    select.value = f.mockup.template;
    const name = text(f.mockup.title, t("review.view_title"));
    return { element: h("div", { class: "inline-form" }, select, name), value: () => ({ template: select.value, title: name.value.trim() }) };
  }
  const fields = wordingFields(f.wording);
  return { element: fields.element, value: fields.value };
}
