import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { backlogPanel } from "./backlog.js";
import { conversation } from "./chat.js";
import { ideasSection } from "./ideas.js";

const STEPS = ["idea", "roles", "stories", "priorities", "criteria", "refinements", "grooming"];

let renderToken = 0;
const POLL_MS = 1500;

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
    this.pending = false; // a blocking request (the backlog review) is running
    this.error = null;
    this.timer = null;
    this.focusComposer = false;
  }

  get current() {
    return this.token === renderToken;
  }

  // Inputs waiting for the AI (or being answered): they run in the server's queue.
  get waiting() {
    return (this.state.queue ?? []).some((item) => item.status !== "failed");
  }

  async send(input) {
    const id = this.state.project.id;
    if (input.kind === "review" || input.kind === "finding") return this.sendBlocking(input);
    this.error = null;
    this.focusComposer = true;
    try {
      // Queued at once: the user can give the next instruction before this one is answered.
      this.state = await api.queueTurn(id, input);
    } catch (error) {
      this.error = errorText(error);
      if (input.kind === "text") this.restoreDraft = input.text;
      this.state = await api.openProject(id).catch(() => this.state);
    }
    if (this.current) this.draw();
  }

  // The backlog review and a finding's decision answer in the same request; nothing else
  // runs meanwhile. The server lets the review wait for a turn that is running.
  async sendBlocking(input) {
    if (this.pending) return;
    this.pending = true;
    this.slow = input.kind === "review" ? "review" : false;
    this.error = null;
    if (input.kind === "review") this.optimistic(input);
    this.draw();
    try {
      const id = this.state.project.id;
      this.state = input.kind === "review" ? await api.review(id)
        : await api.decideFinding(id, input.message_id, input.index, input.data);
    } catch (error) {
      this.error = errorText(error);
      // The server keeps the user's decision even when the AI fails; show it.
      this.state = await api.openProject(this.state.project.id).catch(() => this.state);
    }
    this.pending = false;
    if (this.current) this.draw();
  }

  async retryTurn(item) {
    await this.queueAction(() => api.retryTurn(this.state.project.id, item.id));
  }

  async removeTurn(item) {
    await this.queueAction(() => api.removeTurn(this.state.project.id, item.id));
  }

  async decideIdea(ideaId, decision) {
    await this.queueAction(() => api.decideIdea(this.state.project.id, ideaId, decision));
  }

  async queueAction(work) {
    try {
      this.state = await work();
      this.error = null;
    } catch (error) {
      this.error = errorText(error);
      this.state = await api.openProject(this.state.project.id).catch(() => this.state);
    }
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

  // While inputs wait, look at the server now and then; redraw only when something changed,
  // so what the user is typing or reading is left alone.
  poll() {
    clearTimeout(this.timer);
    if (!this.current || !this.waiting) return;
    this.timer = setTimeout(async () => {
      if (!this.current) return;
      try {
        const next = await api.openProject(this.state.project.id);
        const changed = JSON.stringify(next) !== JSON.stringify(this.state);
        this.state = next;
        if (changed && !this.pending) this.draw();
      } catch {
        // the server may be restarting: try again at the next tick
      }
      this.poll();
    }, POLL_MS);
  }

  async goTo(step) {
    if (this.pending || this.waiting || step === this.state.project.step) return;
    try {
      await api.patchProject(this.state.project.id, { step });
      this.state = await api.openProject(this.state.project.id);
      this.error = null;
    } catch (error) {
      this.error = errorText(error);
    }
    if (this.current) this.draw();
  }

  // The backlog panel, with the client's ideas below its list.
  backlog() {
    const panel = backlogPanel(this.state, () => this.reload(), () => this.send({ kind: "review" }),
      (input) => this.send(input));
    panel.append(ideasSection(this.state, (input) => this.send(input), () => this.reload()));
    return panel;
  }

  draw() {
    const { project } = this.state;
    const box = this.view.querySelector(".composer textarea");
    const typing = box ? { value: box.value, start: box.selectionStart, end: box.selectionEnd,
      focused: document.activeElement === box } : null;
    const before = this.view.querySelector(".conversation")?.children.length ?? 0;
    mount(this.view,
      h("div", { class: "project-head" },
        backLink(),
        h("h1", {}, project.name, " ", h("span", { class: "lang-tag", title: t("projects.language") }, project.language.toUpperCase())),
        project.description ? h("p", { class: "muted" }, project.description) : null),
      stepBar(project.step, (step) => this.goTo(step), this.pending || this.waiting),
      h("div", { class: "workspace" },
        conversation(this.state, (input) => this.send(input),
          { pending: this.pending, error: this.error, slow: this.slow,
            onRetry: (item) => this.retryTurn(item), onRemove: (item) => this.removeTurn(item),
            onPark: (ideaId) => this.decideIdea(ideaId, "park") }),
        this.backlog()));
    const next = this.view.querySelector(".composer textarea");
    // What the user was typing survives a redraw, and so does their place in the box.
    const draft = typing?.value || this.restoreDraft;
    this.restoreDraft = null;
    if (next && draft) {
      next.value = draft;
      if (typing) next.setSelectionRange(typing.start, typing.end);
    }
    this.view.querySelector(".step.current")?.scrollIntoView({ block: "nearest", inline: "center" });
    // Follow the conversation when it grew, not on every redraw of an unchanged one.
    const grew = (this.view.querySelector(".conversation")?.children.length ?? 0) !== before;
    if (this.state.messages.length && (grew || this.focusComposer)) next?.scrollIntoView({ block: "end" });
    if (!this.pending && (this.focusComposer || typing?.focused || !typing)) next?.focus({ preventScroll: true });
    this.focusComposer = false;
    this.poll();
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
