// The guided conversation: message history, answer cards, next steps, composer.
// Only the latest assistant message is interactive; older cards show what was chosen.

import { h } from "../dom.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { renderTree } from "../mockup/render.js";
import { issueList } from "../ui.js";
import { openMockupViewer } from "../mockup/viewer.js";

// Resume actions (from the server) that move the process to a step.
const ACTION_STEP = {
  continue_conversation: null,
  continue_roles: "roles",
  go_stories: "stories",
  continue_stories: "stories",
  choose_priority: "priorities",
  continue_criteria: "criteria",
  next_story: "criteria",
  enter_refinement: "refinements",
  review_backlog: "grooming",
};

/**
 * @param state   project state from the API
 * @param send    async (input) => void, posts one turn
 * @param options { pending, error } for the in-flight turn
 */
export function conversation(state, send, { pending = false, error = null, slow = false } = {}) {
  const { messages } = state;
  const last = messages[messages.length - 1];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const live = !pending && last && last === lastAssistant ? last : null;

  return h("section", { class: `conversation card ${pending ? "busy" : ""}`, "aria-live": "polite" },
    messages.map((m) => (m.role === "user" ? userMessage(m) : assistantMessage(m, m === live, send, state))),
    pending ? h("div", { class: "message assistant thinking" }, author("assistant"),
      h("p", {}, t(slow ? "chat.thinking_mockup" : "chat.thinking"))) : null,
    error ? errorCard(error, send) : null,
    !pending && !error ? resumeCard(state, last, lastAssistant, send) : null,
    composer(state, send, pending));
}

function author(role) {
  return h("div", { class: "message-author" }, t(role === "user" ? "chat.you" : "chat.assistant"));
}

function userMessage(message) {
  const input = message.content.input ?? {};
  // Answers, role choices and added stories are shown on the card they answer.
  if (["answer", "roles", "stories", "focus", "criteria"].includes(input.kind)) return null;
  let text;
  switch (input.kind) {
    case "text": text = input.text; break;
    case "next": text = input.label; break;
    default: text = message.content.text ?? "";
  }
  return h("div", { class: "message user" }, author("user"), h("p", {}, text));
}

function assistantMessage(message, live, send, state) {
  const c = message.content;
  return h("div", { class: "message assistant" },
    author("assistant"),
    h("p", {}, c.text),
    c.question ? questionCard(message, live, send) : null,
    c.roles ? rolesCard(message, live, send, state) : null,
    c.stories ? storiesCard(message, live, send) : null,
    c.priority ? priorityCard(message, live, send, state) : null,
    c.proposal ? proposalCard(message, live, send, state) : null,
    live && c.next_steps?.length ? nextSteps(c.next_steps, send) : null);
}

// --- question ------------------------------------------------------------

function questionCard(message, live, send) {
  const q = message.content.question;
  if (q.answer || !live) {
    const a = q.answer;
    const summary = !a ? t("chat.not_answered")
      : a.skipped ? t("chat.skipped") : [...a.selected, a.other].filter(Boolean).join(", ");
    return h("div", { class: "card-block answered" },
      h("div", { class: "card-title" }, q.text), h("p", { class: "muted" }, summary));
  }

  const chosen = new Set();
  const answer = (extra = {}) => send({ kind: "answer", message_id: message.id, selected: [...chosen], ...extra });
  const otherInput = h("input", { type: "text", maxlength: 300, placeholder: t("chat.other_hint"),
    "aria-label": t("chat.other") });
  const otherRow = h("form", { class: "inline-form", hidden: true, onsubmit: (e) => {
    e.preventDefault();
    if (otherInput.value.trim()) answer({ other: otherInput.value });
  } }, otherInput, h("button", { type: "submit", class: "primary" }, t("chat.send")));
  const confirm = h("button", { type: "button", class: "primary", disabled: true,
    onclick: () => answer() }, t("chat.confirm_choice"));

  const options = q.options.map((option) => {
    const button = h("button", { type: "button", class: "choice option" }, option);
    if (q.multi_select) {
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => {
        chosen.has(option) ? chosen.delete(option) : chosen.add(option);
        button.setAttribute("aria-pressed", String(chosen.has(option)));
        confirm.disabled = chosen.size === 0;
      });
    } else {
      button.addEventListener("click", () => { chosen.add(option); answer(); });
    }
    return button;
  });

  return h("div", { class: "card-block" },
    h("div", { class: "card-title" }, q.text, q.multi_select ? h("span", { class: "hint" }, ` ${t("chat.multi_hint")}`) : null),
    h("div", { class: "choices" },
      options,
      h("button", { type: "button", class: "choice quiet", onclick: () => {
        otherRow.hidden = false; otherInput.focus();
      } }, t("chat.other")),
      h("button", { type: "button", class: "choice quiet", onclick: () => answer({ skipped: true, selected: [] }) },
        t("chat.skip"))),
    otherRow,
    q.multi_select ? h("div", { class: "card-actions" }, confirm) : null);
}

// --- roles ---------------------------------------------------------------

function rolesCard(message, live, send, state) {
  const c = message.content;
  if (c.roles_confirmed || !live) {
    return h("div", { class: "card-block answered" },
      h("div", { class: "card-title" }, t("chat.roles_title")),
      h("p", { class: "muted" }, c.roles_confirmed ? c.roles_confirmed.join(", ") : t("chat.not_answered")));
  }

  const current = new Set(state.roles.map((r) => r.name.toLowerCase()));
  const list = h("ul", { class: "role-list" });
  const roleOf = new Map();
  const addRole = (role, checked) => {
    const box = h("input", { type: "checkbox", checked });
    roleOf.set(box, role);
    list.append(h("li", {}, h("label", { class: "check" }, box,
      h("span", {}, h("strong", {}, role.name), role.description ? h("span", { class: "muted" }, ` ${role.description}`) : null))));
  };
  c.roles.forEach((r) => addRole(r, r.recommended || current.has(r.name.toLowerCase())));

  const newName = h("input", { type: "text", maxlength: 60, placeholder: t("chat.add_role_hint"),
    "aria-label": t("chat.add_role") });
  const addForm = h("form", { class: "inline-form", onsubmit: (e) => {
    e.preventDefault();
    const name = newName.value.trim();
    if (!name) return;
    addRole({ name, description: "" }, true);
    newName.value = "";
    newName.focus();
  } }, newName, h("button", { type: "submit" }, t("chat.add_role")));

  const status = h("p", { class: "hint", role: "status" });
  const confirm = () => {
    const roles = [...list.querySelectorAll("input:checked")].map((box) =>
      ({ name: roleOf.get(box).name, description: roleOf.get(box).description ?? "" }));
    if (!roles.length) { status.textContent = t("chat.roles_none"); return; }
    send({ kind: "roles", message_id: message.id, roles });
  };

  return h("div", { class: "card-block" },
    h("div", { class: "card-title" }, t("chat.roles_title")),
    list, addForm, status,
    h("div", { class: "card-actions" },
      h("button", { type: "button", class: "primary", onclick: confirm }, t("chat.confirm_roles"))));
}

// --- stories -------------------------------------------------------------

function storyTitle(story) {
  const phrase = story.role_phrase.charAt(0).toUpperCase() + story.role_phrase.slice(1);
  return t("story.title", { role: phrase, action: story.action, benefit: story.benefit.replace(/\.$/, "") });
}

function storiesCard(message, live, send) {
  const c = message.content;
  if (c.stories_added || !live) {
    const added = c.stories_added?.keys ?? [];
    return h("div", { class: "card-block answered" },
      h("div", { class: "card-title" }, t("chat.stories_title", { count: c.stories.length })),
      h("p", { class: "muted" }, added.length ? t("chat.stories_added", { keys: added.join(", ") }) : t("chat.stories_not_added")));
  }

  const boxes = c.stories.map(() => h("input", { type: "checkbox", checked: true }));
  const addSelected = h("button", { type: "button" }, t("chat.add_selected"));
  const refresh = () => {
    const count = boxes.filter((b) => b.checked).length;
    addSelected.disabled = count === 0;
    addSelected.textContent = t("chat.add_selected_count", { count });
  };
  boxes.forEach((b) => b.addEventListener("change", refresh));
  refresh();
  addSelected.addEventListener("click", () => send({ kind: "stories", message_id: message.id,
    selected: boxes.flatMap((b, i) => (b.checked ? [i] : [])) }));

  return h("div", { class: "card-block" },
    h("div", { class: "card-title" }, t("chat.stories_title", { count: c.stories.length })),
    h("ol", { class: "story-cards" }, c.stories.map((story, i) => h("li", {},
      h("label", { class: "check story-check" }, boxes[i],
        h("span", {}, h("span", { class: "story-role" }, story.role_name), storyTitle(story)))))),
    h("div", { class: "card-actions" },
      h("button", { type: "button", class: "quiet-button",
        onclick: () => send({ kind: "next", label: t("chat.suggest_different"), step: "stories" }) },
        t("chat.suggest_different")),
      addSelected,
      h("button", { type: "button", class: "primary", onclick: () =>
        send({ kind: "stories", message_id: message.id, selected: c.stories.map((_, i) => i) }) },
        t("chat.add_all"))));
}

// --- priority ------------------------------------------------------------

function priorityCard(message, live, send, state) {
  const card = message.content.priority;
  const byKey = new Map(state.stories.map((s) => [s.key, s]));
  const recommended = byKey.get(card.story_key);
  const summary = (key) => {
    const story = byKey.get(key);
    return story ? `${key}: ${story.title}` : key;
  };

  if (card.chosen || !live || !recommended) {
    return h("div", { class: "card-block answered" },
      h("div", { class: "card-title" }, t("chat.priority_title")),
      h("p", { class: "muted" }, card.chosen
        ? t(card.chosen.agreed ? "chat.priority_agreed" : "chat.priority_other", { story: summary(card.chosen.key) })
        : t("chat.priority_recommended", { story: summary(card.story_key) })));
  }

  const focus = (story) => send({ kind: "focus", message_id: message.id, story_id: story.id });
  const others = h("div", { class: "choice-list", hidden: true },
    h("p", { class: "hint" }, t("chat.priority_pick")),
    state.stories.filter((s) => s.key !== card.story_key).map((story) =>
      h("button", { type: "button", class: "choice story-choice", onclick: () => focus(story) },
        h("span", { class: "story-key" }, story.key), " ", story.title)));

  return h("div", { class: "card-block recommendation" },
    h("div", { class: "card-title" }, t("chat.priority_title")),
    h("p", { class: "recommended-story" }, h("span", { class: "story-key" }, recommended.key), " ", recommended.title),
    h("p", { class: "reason" }, h("strong", {}, t("chat.priority_why")), " ", card.reason),
    h("div", { class: "card-actions" },
      h("button", { type: "button", onclick: () => { others.hidden = !others.hidden; } }, t("chat.priority_choose_other")),
      h("button", { type: "button", class: "primary", onclick: () => focus(recommended) }, t("chat.priority_agree"))),
    others);
}

// --- criteria and mockup proposal ----------------------------------------

function proposalCard(message, live, send, state) {
  const p = message.content.proposal;
  const preview = h("div", { class: "proposal-mockup" }, renderTree(p.mockup));
  const highlight = (id, on) => {
    if (!id) return;
    preview.querySelectorAll(`[data-component-id="${CSS.escape(id)}"]`).forEach((el) => el.classList.toggle("wf-highlight", on));
  };
  const open = () => openMockupViewer({ title: p.mockup.title, version: "·", tree: p.mockup });
  const mockupColumn = h("div", { class: "proposal-side" },
    h("button", { type: "button", class: "proposal-preview", onclick: open, "aria-label": t("mockup.open", { title: p.mockup.title }) }, preview),
    h("button", { type: "button", class: "small", onclick: open }, t("chat.open_mockup")));

  if (p.decided || !live) {
    return h("div", { class: "card-block answered proposal" },
      h("div", { class: "card-title" }, t("chat.proposal_title", { key: p.story_key })),
      h("p", { class: "muted" }, p.decided
        ? t("chat.proposal_decided", { kept: p.decided.kept, rejected: p.decided.rejected })
        : t("chat.proposal_not_decided")),
      mockupColumn);
  }

  // Each row: { index, text, state: pending | accepted | edited | rejected }
  const rows = p.criteria.map((c, index) => ({ index, text: c.text, component: c.component_id, state: "pending", issues: c.issues ?? [] }));
  const list = h("ol", { class: "criteria-review" });

  const drawRows = () => {
    list.replaceChildren(...rows.map((row, i) => criterionRow(row, () => drawRows(), (on) => highlight(row.component, on), () => {
      rows.splice(i, 1); drawRows();
    })));
  };
  drawRows();

  const submit = () => send({ kind: "criteria", message_id: message.id, items: rows
    .filter((row) => row.state !== "rejected" && row.text.trim())
    .map((row) => (row.index === null ? { index: null, text: row.text }
      : row.state === "edited" ? { index: row.index, text: row.text } : { index: row.index })) });

  return h("div", { class: "card-block proposal" },
    h("div", { class: "card-title" }, t("chat.proposal_title", { key: p.story_key })),
    h("div", { class: "proposal-body" },
      h("div", {}, list,
        h("div", { class: "card-actions" },
          h("button", { type: "button", class: "quiet-button", onclick: () => {
            rows.push({ index: null, text: "", component: null, state: "editing" }); drawRows();
            list.querySelector("li:last-child input")?.focus();
          } }, `+ ${t("chat.add_criterion")}`),
          h("button", { type: "button", class: "primary", onclick: submit }, t("chat.confirm_all")))),
      mockupColumn));
}

function criterionRow(row, redraw, highlight, drop) {
  const editing = row.state === "editing";
  const input = h("input", { type: "text", maxlength: 300, "aria-label": t("chat.criterion_text") });
  input.value = row.text;
  const done = async () => {
    row.text = input.value.trim();
    if (!row.text && row.index === null) { drop(); return; }
    row.state = row.index === null ? "edited" : (row.text === row.original ? "accepted" : "edited");
    row.issues = await api.checkCriteria([row.text]).then((r) => r[0]).catch(() => []);
    redraw();
  };
  const item = h("li", { class: `criterion ${row.state}`, onmouseenter: () => highlight(true), onmouseleave: () => highlight(false) },
    editing
      ? h("form", { class: "inline-form", onsubmit: (e) => { e.preventDefault(); done(); } }, input,
        h("button", { type: "submit", class: "small primary" }, t("chat.save_criterion")))
      : h("span", { class: "criterion-text" }, row.text,
        row.index === null ? h("span", { class: "hint" }, ` (${t("chat.added")})`) : null,
        row.state === "edited" && row.index !== null ? h("span", { class: "hint" }, ` (${t("chat.edited")})`) : null,
        row.state === "rejected" ? null : issueList(row.issues)),
    editing ? null : h("span", { class: "criterion-actions" },
      row.state === "rejected"
        ? h("button", { type: "button", class: "small", onclick: () => { row.state = "pending"; redraw(); } }, t("chat.restore"))
        : [
          h("button", { type: "button", class: `small ${row.state === "accepted" ? "chosen" : ""}`, "aria-pressed": String(row.state === "accepted"),
            onclick: () => { row.state = "accepted"; redraw(); } }, `✓ ${t("chat.accept")}`),
          h("button", { type: "button", class: "small", onclick: () => {
            row.original ??= row.text; row.state = "editing"; redraw();
          } }, `✎ ${t("chat.edit")}`),
          h("button", { type: "button", class: "small", onclick: () => {
            if (row.index === null) drop(); else { row.state = "rejected"; redraw(); }
          } }, `✗ ${t("chat.remove")}`),
        ]));
  if (editing) setTimeout(() => input.focus(), 0);
  return item;
}

// --- next steps, resume, errors, composer --------------------------------

function nextSteps(steps, send) {
  return h("div", { class: "choices next-steps" }, steps.map((step, i) => h("button", {
    type: "button",
    class: i === 0 ? "choice primary" : "choice",
    onclick: () => (step.kind === "end_meeting" ? endMeeting()
      : send({ kind: "next", label: step.label, step: step.step })),
  }, step.label)));
}

function endMeeting() {
  location.hash = "#/";
}

function resumeCard(state, last, lastAssistant, send) {
  const { resume, project } = state;
  if (resume.kind === "start") {
    return h("div", { class: "message assistant" }, author("assistant"), h("p", {}, t("resume.start")));
  }
  if (last && last === lastAssistant && lastAssistant.content.step === project.step) return null;
  if (last && last.role === "user") {
    // The AI never answered this input (it failed earlier): offer to ask again.
    return errorCard(t("chat.no_answer"), send);
  }

  return h("div", { class: "message assistant" },
    author("assistant"),
    h("p", {}, t("resume.continue", { step: t(`step.${project.step}`) })),
    h("div", { class: "choices" }, resume.actions.map((action, i) => h("button", {
      type: "button",
      class: i === 0 ? "choice primary" : "choice",
      onclick: () => (action === "end_meeting" ? endMeeting()
        : send({ kind: "next", label: t(`action.${action}`), step: ACTION_STEP[action] ?? null })),
    }, t(`action.${action}`)))));
}

function errorCard(error, send) {
  return h("div", { class: "notice error", role: "alert" },
    h("p", {}, error),
    h("button", { type: "button", onclick: () => send({ kind: "retry" }) }, t("chat.retry")));
}

function composer(state, send, pending) {
  const start = state.messages.length === 0;
  const box = h("textarea", { rows: start ? 3 : 2, maxlength: 4000, disabled: pending,
    placeholder: t(start ? "chat.idea_hint" : "chat.free_hint"), "aria-label": t("chat.free_hint") });
  const submit = () => {
    const text = box.value.trim();
    if (text) send({ kind: "text", text });
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  return h("form", { class: "composer", onsubmit: (e) => { e.preventDefault(); submit(); } },
    box, h("button", { type: "submit", class: "primary", disabled: pending }, t("chat.send")));
}
