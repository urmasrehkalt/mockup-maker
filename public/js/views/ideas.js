// The client's ideas that are not in the backlog: kept beside it until they become a new
// view or a refinement, or are dropped. Adding and dropping work without the AI; turning an
// idea into a view or a refinement goes through the conversation (and its confirmation cards).

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";

/**
 * @param state   project state
 * @param send    (input) => queues a conversation input
 * @param reload  async () => reloads the project state and redraws
 */
export function ideasSection(state, send, reload) {
  const { ideas, project, stories } = state;
  const current = stories.find((s) => s.id === project.current_story_id);
  const status = h("div", { class: "form-status", role: "status" });

  async function act(work) {
    mount(status);
    try {
      await work();
      await reload();
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
    }
  }

  const box = h("input", { type: "text", maxlength: 1000, placeholder: t("ideas.add_placeholder"),
    "aria-label": t("ideas.add_placeholder") });
  const add = () => {
    const text = box.value.trim();
    if (text) act(() => api.addIdea(project.id, text));
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); add(); }
  });

  return h("section", { class: "ideas", "aria-labelledby": "ideas-title" },
    h("h3", { id: "ideas-title" }, t("ideas.title"), h("span", { class: "count" }, ` ${ideas.length}`)),
    ideas.length
      ? h("ul", { class: "idea-list" }, ideas.map((idea) => h("li", { class: "idea" },
        h("p", {}, idea.text),
        h("div", { class: "idea-actions" },
          h("button", { type: "button", class: "small", onclick: () =>
            send({ kind: "idea", idea_id: idea.id, decision: "new_view" }) }, t("ideas.make_view")),
          current ? h("button", { type: "button", class: "small", onclick: () =>
            send({ kind: "idea", idea_id: idea.id, decision: "refine" }) }, t("ideas.refine_story", { key: current.key })) : null,
          h("button", { type: "button", class: "small", onclick: () =>
            act(() => api.decideIdea(project.id, idea.id, "dismiss")) }, t("ideas.dismiss"))))))
      : h("p", { class: "hint" }, t("ideas.empty")),
    h("div", { class: "inline-form" }, box, h("button", { type: "button", class: "small", onclick: add }, t("ideas.add"))),
    status);
}
