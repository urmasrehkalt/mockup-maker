// Backlog panel beside the conversation: manual add, edit, delete, reorder and undo.
// Works without the AI; every change goes straight to the backlog API.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { openStoryEditor } from "./story-editor.js";

/**
 * @param state   project state
 * @param reload  async () => void, reloads the project state and redraws
 */
export function backlogPanel(state, reload) {
  const { stories, undo, project } = state;
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

  const move = (ids) => act(() => api.reorderStories(project.id, ids));
  const edit = (story) => openStoryEditor(state, story, reload);
  const undoLabel = undo ? t(`undo.${undo.action}`, undo.params) : null;

  return h("aside", { class: "backlog card", "aria-labelledby": "backlog-title" },
    h("div", { class: "panel-head" },
      h("h2", { id: "backlog-title" }, t("backlog.title"), h("span", { class: "count" }, ` ${stories.length}`)),
      h("div", { class: "panel-actions" },
        h("button", { type: "button", class: "small", disabled: !undo,
          title: undoLabel ? t("backlog.undo_what", { what: undoLabel }) : t("backlog.undo_nothing"),
          onclick: () => act(() => api.undo(project.id)) }, `↶ ${t("backlog.undo")}`),
        h("button", { type: "button", class: "small primary", onclick: () => edit(null) }, `+ ${t("backlog.add")}`))),
    undoLabel ? h("p", { class: "hint undo-hint" }, t("backlog.undo_what", { what: undoLabel })) : null,
    status,
    stories.length
      ? h("ol", { class: "story-list" }, stories.map((story, i) =>
        storyRow(story, i, stories, move, edit, story.id === project.current_story_id)))
      : h("p", { class: "muted" }, t("backlog.empty")));
}

const warned = (story) => story.criteria.filter((c) => c.issues.length).length;

function storyRow(story, index, stories, move, edit, current) {
  const ids = stories.map((s) => s.id);
  const shifted = (to) => {
    const next = ids.filter((id) => id !== story.id);
    next.splice(to, 0, story.id);
    return next;
  };

  const row = h("li", { class: `story-row ${current ? "current" : ""}`, draggable: "true", dataset: { id: story.id } },
    h("span", { class: "drag-handle", "aria-hidden": "true", title: t("backlog.drag") }, "⋮⋮"),
    h("button", { type: "button", class: "story-open", onclick: () => edit(story),
      "aria-label": t("backlog.edit_story", { key: story.key }) },
      h("span", { class: "story-meta" },
        h("span", { class: "story-key" }, story.key),
        current ? h("span", { class: "current-tag" }, t("backlog.current")) : null,
        h("span", { class: `status status-${story.status}` }, t(`status.${story.status}`)),
        story.size ? h("span", { class: "size" }, story.size) : null,
        story.criteria.length ? h("span", { class: "muted" }, t("backlog.criteria_count", { count: story.criteria.length })) : null,
        warned(story) ? h("span", { class: "warn-count", title: t("backlog.untestable") }, `⚠ ${warned(story)}`) : null,
        story.mockup_ids.length ? h("span", { class: "muted", title: t("mockup.section") }, t("backlog.mockup_count", { count: story.mockup_ids.length })) : null,
        story.open_questions.length ? h("span", { class: "open-q" }, `? ${story.open_questions.length}`) : null,
        story.status !== "ready" && !story.readiness.length ? h("span", { class: "dor-ok", title: t("ready.summary_ok") }, "DoR ✓") : null,
        h("span", { class: "origin", title: t(`backlog.origin.${story.origin}`) }, story.origin === "ai" ? "AI" : "✎")),
      h("span", { class: "story-title" }, story.title)),
    h("span", { class: "row-moves" },
      h("button", { type: "button", class: "icon", disabled: index === 0,
        "aria-label": t("backlog.move_up", { key: story.key }), onclick: () => move(shifted(index - 1)) }, "↑"),
      h("button", { type: "button", class: "icon", disabled: index === stories.length - 1,
        "aria-label": t("backlog.move_down", { key: story.key }), onclick: () => move(shifted(index + 1)) }, "↓")));

  row.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", String(story.id));
    e.dataTransfer.effectAllowed = "move";
    row.classList.add("dragging");
  });
  row.addEventListener("dragend", () => row.classList.remove("dragging"));
  row.addEventListener("dragover", (e) => {
    e.preventDefault();
    const after = e.clientY > row.getBoundingClientRect().top + row.offsetHeight / 2;
    row.classList.toggle("drop-before", !after);
    row.classList.toggle("drop-after", after);
  });
  row.addEventListener("dragleave", () => row.classList.remove("drop-before", "drop-after"));
  row.addEventListener("drop", (e) => {
    e.preventDefault();
    const after = row.classList.contains("drop-after");
    row.classList.remove("drop-before", "drop-after");
    const dragged = Number(e.dataTransfer.getData("text/plain"));
    if (!dragged || dragged === story.id) return;
    const next = ids.filter((id) => id !== dragged);
    next.splice(next.indexOf(story.id) + (after ? 1 : 0), 0, dragged);
    move(next);
  });
  return row;
}
