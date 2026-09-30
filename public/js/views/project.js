import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";

const STEPS = ["idea", "roles", "stories", "priorities", "criteria", "refinements", "grooming"];

// Resume actions that move the process to a step. Actions without a handler
// here are not shown yet; the stories that implement them register them.
const ACTION_STEP = {
  continue_roles: "roles",
  go_stories: "stories",
  continue_stories: "stories",
  choose_priority: "priorities",
  continue_criteria: "criteria",
  next_story: "criteria",
  enter_refinement: "refinements",
  review_backlog: "grooming",
};

let renderToken = 0;

export async function renderProject(view, id) {
  const token = ++renderToken;
  mount(view, h("p", { class: "muted", "aria-busy": "true" }, "…"));
  let state;
  try {
    state = await api.openProject(id);
  } catch (error) {
    if (token === renderToken) mount(view, backLink(), notice(errorText(error), "error"));
    return;
  }
  if (token !== renderToken) return;
  draw(view, state);
}

function draw(view, state) {
  const { project } = state;

  async function goTo(step) {
    if (step === project.step) return;
    try {
      await api.patchProject(project.id, { step });
      draw(view, await api.openProject(project.id));
    } catch (error) {
      mount(errors, notice(errorText(error), "error"));
    }
  }

  const errors = h("div", { class: "form-status" });
  mount(view,
    h("div", { class: "project-head" },
      backLink(),
      h("h1", {}, project.name),
      project.description ? h("p", { class: "muted" }, project.description) : null),
    stepBar(project.step, goTo),
    errors,
    h("section", { class: "conversation card", "aria-label": t("chat.assistant") },
      state.messages.map(message),
      resumeCard(state, goTo)));
  view.querySelector(".step.current")?.scrollIntoView({ block: "nearest", inline: "center" });
}

function backLink() {
  return h("a", { class: "back", href: "#/" }, `← ${t("projects.back")}`);
}

function stepBar(current, goTo) {
  const index = STEPS.indexOf(current);
  return h("nav", { class: "steps", "aria-label": t("steps.label") },
    h("ol", {}, STEPS.map((step, i) => h("li", {},
      h("button", {
        type: "button",
        class: `step ${i < index ? "past" : ""} ${i === index ? "current" : ""}`,
        "aria-current": i === index ? "step" : false,
        onclick: () => goTo(step),
      }, h("span", { class: "step-number" }, String(i + 1)), t(`step.${step}`))))));
}

function message(msg) {
  const { text, options } = msg.content;
  return h("div", { class: `message ${msg.role}` },
    h("div", { class: "message-author" }, t(msg.role === "user" ? "chat.you" : "chat.assistant")),
    text ? h("p", {}, text) : null,
    Array.isArray(options) && options.length
      ? h("ul", { class: "option-list" }, options.map((o) => h("li", {}, String(o.label ?? o))))
      : null);
}

function resumeCard(state, goTo) {
  const { resume, project } = state;
  if (resume.kind === "start") {
    return h("div", { class: "message assistant resume" },
      h("div", { class: "message-author" }, t("chat.assistant")),
      h("p", {}, t("resume.start")));
  }
  const actions = resume.actions.filter((a) => a in ACTION_STEP || a === "end_meeting");
  return h("div", { class: "message assistant resume" },
    h("div", { class: "message-author" }, t("chat.assistant")),
    h("p", {}, t("resume.continue", { step: t(`step.${project.step}`) })),
    h("div", { class: "choices" }, actions.map((action, i) => h("button", {
      type: "button",
      class: i === 0 ? "choice primary" : "choice",
      onclick: () => (action === "end_meeting" ? (location.hash = "#/") : goTo(ACTION_STEP[action])),
    }, t(`action.${action}`)))));
}
