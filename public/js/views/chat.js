// The guided conversation: message history, answer cards, next steps, composer.
// Only the latest assistant message is interactive; older cards show what was chosen.

import { h } from "../dom.js";
import { t } from "../i18n.js";

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
export function conversation(state, send, { pending = false, error = null } = {}) {
  const { messages } = state;
  const last = messages[messages.length - 1];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const live = !pending && last && last === lastAssistant ? last : null;

  return h("section", { class: `conversation card ${pending ? "busy" : ""}`, "aria-live": "polite" },
    messages.map((m) => (m.role === "user" ? userMessage(m) : assistantMessage(m, m === live, send, state))),
    pending ? h("div", { class: "message assistant thinking" }, author("assistant"), h("p", {}, t("chat.thinking"))) : null,
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
  if (["answer", "roles", "stories", "focus"].includes(input.kind)) return null;
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
