import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { backlogPanel } from "./backlog.js";
import { conversation } from "./chat.js";

const STEPS = ["idea", "roles", "stories", "priorities", "criteria", "refinements", "grooming"];

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
  new ProjectPage(view, state, token).draw();
}

class ProjectPage {
  constructor(view, state, token) {
    this.view = view;
    this.state = state;
    this.token = token;
    this.pending = false;
    this.error = null;
  }

  get current() {
    return this.token === renderToken;
  }

  async send(input) {
    if (this.pending) return;
    this.pending = true;
    this.error = null;
    if (input.kind !== "retry") this.optimistic(input);
    this.draw();
    try {
      this.state = await api.turn(this.state.project.id, input);
    } catch (error) {
      this.error = errorText(error);
      // The server keeps the user's decision even when the AI fails; show it.
      this.state = await api.openProject(this.state.project.id).catch(() => this.state);
    }
    this.pending = false;
    if (this.current) this.draw();
  }

  // Show the user's input at once; the server's state replaces it when the turn returns.
  optimistic(input) {
    this.state = { ...this.state, messages: [...this.state.messages,
      { id: -1, role: "user", content: { input }, created_at: "" }] };
  }

  async reload() {
    this.state = await api.openProject(this.state.project.id);
    if (this.current) this.draw();
    return this.state;
  }

  async goTo(step) {
    if (this.pending || step === this.state.project.step) return;
    try {
      await api.patchProject(this.state.project.id, { step });
      this.state = await api.openProject(this.state.project.id);
      this.error = null;
    } catch (error) {
      this.error = errorText(error);
    }
    if (this.current) this.draw();
  }

  draw() {
    const { project } = this.state;
    mount(this.view,
      h("div", { class: "project-head" },
        backLink(),
        h("h1", {}, project.name),
        project.description ? h("p", { class: "muted" }, project.description) : null),
      stepBar(project.step, (step) => this.goTo(step), this.pending),
      h("div", { class: "workspace" },
        conversation(this.state, (input) => this.send(input), { pending: this.pending, error: this.error }),
        backlogPanel(this.state, () => this.reload())));
    this.view.querySelector(".step.current")?.scrollIntoView({ block: "nearest", inline: "center" });
    const end = this.view.querySelector(".composer");
    if (this.state.messages.length) end?.scrollIntoView({ block: "end" });
    if (!this.pending) end?.querySelector("textarea")?.focus({ preventScroll: true });
  }
}

function backLink() {
  return h("a", { class: "back", href: "#/" }, `← ${t("projects.back")}`);
}

function stepBar(current, goTo, disabled) {
  const index = STEPS.indexOf(current);
  return h("nav", { class: "steps", "aria-label": t("steps.label") },
    h("ol", {}, STEPS.map((step, i) => h("li", {},
      h("button", {
        type: "button",
        class: `step ${i < index ? "past" : ""} ${i === index ? "current" : ""}`,
        "aria-current": i === index ? "step" : false,
        disabled,
        onclick: () => goTo(step),
      }, h("span", { class: "step-number" }, String(i + 1)), t(`step.${step}`))))));
}
