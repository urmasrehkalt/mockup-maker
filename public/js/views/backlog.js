// Backlog panel beside the conversation: manual add, edit, delete, reorder, MVP line and undo.
// Works without the AI; every change goes straight to the backlog API.
//
// The list is one ordered sequence of items: story ids and, when set, the "mvp"
// marker for the MVP line. Dragging and the move buttons work on that sequence,
// so stories and the line move the same way.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { openStoryEditor } from "./story-editor.js";
import { openStoryMap } from "./story-map.js";
import { openTrackerDialog, trackerStatus } from "./tracker.js";

const MVP = "mvp";

/**
 * @param state   project state
 * @param reload  async () => state, reloads the project state and redraws
 */
export function backlogPanel(state, reload, review) {
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

  const items = stories.map((s) => s.id);
  if (project.mvp_count !== null && project.mvp_count !== undefined) items.splice(project.mvp_count, 0, MVP);

  const commit = (next) => act(() => {
    const line = next.indexOf(MVP);
    const ids = next.filter((item) => item !== MVP);
    return api.reorderStories(project.id, ids, line === -1 ? { keep_mvp: false } : { mvp_count: line });
  });
  const moved = (item, to) => {
    const next = items.filter((x) => x !== item);
    next.splice(to, 0, item);
    return next;
  };
  const edit = (story) => openStoryEditor(state, story, reload);
  const undoLabel = undo ? t(`undo.${undo.action}`, undo.params) : null;
  const hasLine = items.includes(MVP);

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
      ? h("ol", { class: "story-list" }, items.map((item, index) => {
        const row = item === MVP
          ? mvpRow(index, items.length, commit, moved, () => commit(items.filter((x) => x !== MVP)))
          : storyRow(stories.find((s) => s.id === item), index, items.length, edit, commit, moved,
            item === project.current_story_id);
        draggable(row, item, items, commit);
        return row;
      }))
      : h("p", { class: "muted" }, t("backlog.empty")),
    stories.length ? h("div", { class: "backlog-foot" },
      h("button", { type: "button", class: "small review-button", onclick: review }, `✦ ${t("review.button")}`),
      trackerButton(state, reload),
      h("button", { type: "button", class: "small", onclick: () => openStoryMap(state, reload) }, `▦ ${t("storymap.button")}`),
      h("a", { class: "button-link small", href: `/api/projects/${project.id}/export.md`, download: "" }, `⭳ ${t("export.markdown")}`),
      h("a", { class: "button-link small", href: `/api/projects/${project.id}/export.csv`, download: "" }, `⭳ ${t("export.csv")}`),
      hasLine ? null : h("button", { type: "button", class: "small add-mvp",
        onclick: () => commit(moved(MVP, Math.min(3, stories.length))) }, `+ ${t("backlog.add_mvp")}`)) : null);
}

// Shown once the server confirms a tracker is configured.
function trackerButton(state, reload) {
  const button = h("button", { type: "button", class: "small", hidden: true,
    onclick: () => openTrackerDialog(state, reload) }, `↗ ${t("tracker.button")}`);
  trackerStatus().then((s) => { button.hidden = !s.configured; });
  return button;
}

const warned = (story) => story.criteria.filter((c) => c.issues.length).length;

function moveButtons(label, index, count, item, commit, moved) {
  return h("span", { class: "row-moves" },
    h("button", { type: "button", class: "icon", disabled: index === 0,
      "aria-label": t("backlog.move_up", { key: label }), onclick: () => commit(moved(item, index - 1)) }, "↑"),
    h("button", { type: "button", class: "icon", disabled: index === count - 1,
      "aria-label": t("backlog.move_down", { key: label }), onclick: () => commit(moved(item, index + 1)) }, "↓"));
}

function mvpRow(index, count, commit, moved, remove) {
  return h("li", { class: "mvp-line", draggable: "true", role: "separator", "aria-label": t("backlog.mvp_line") },
    h("span", { class: "drag-handle", "aria-hidden": "true" }, "⋮⋮"),
    h("span", { class: "mvp-label" }, t("backlog.mvp_line"), h("span", { class: "hint" }, ` ${t("backlog.mvp_hint")}`)),
    h("span", { class: "mvp-actions" },
      moveButtons(t("backlog.mvp_line"), index, count, MVP, commit, moved),
      h("button", { type: "button", class: "icon", "aria-label": t("backlog.remove_mvp"),
        onclick: remove }, "✕")));
}

function storyRow(story, index, count, edit, commit, moved, current) {
  return h("li", { class: `story-row ${current ? "current" : ""} ${story.in_mvp ? "in-mvp" : ""}`, draggable: "true", dataset: { id: story.id } },
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
        story.tracker_id ? h("span", { class: "muted", title: t("tracker.already", { id: story.tracker_id }) }, `↗ #${story.tracker_id}`) : null,
        h("span", { class: "origin", title: t(`backlog.origin.${story.origin}`) }, story.origin === "ai" ? "AI" : "✎")),
      h("span", { class: "story-title" }, story.title)),
    moveButtons(story.key, index, count, story.id, commit, moved));
}

// Drag and drop over the whole sequence (stories and the MVP line alike).
function draggable(row, item, items, commit) {
  row.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", String(item));
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
    const raw = e.dataTransfer.getData("text/plain");
    const dragged = raw === MVP ? MVP : Number(raw);
    if (!raw || dragged === item) return;
    const next = items.filter((x) => x !== dragged);
    next.splice(next.indexOf(item) + (after ? 1 : 0), 0, dragged);
    commit(next);
  });
}
