// Backlog panel beside the conversation. Read-only for now; #6 adds manual editing.

import { h } from "../dom.js";
import { t } from "../i18n.js";

export function backlogPanel(state) {
  const { stories } = state;
  return h("aside", { class: "backlog card", "aria-labelledby": "backlog-title" },
    h("div", { class: "panel-head" },
      h("h2", { id: "backlog-title" }, t("backlog.title")),
      h("span", { class: "count" }, String(stories.length))),
    stories.length
      ? h("ol", { class: "story-list" }, stories.map(storyRow))
      : h("p", { class: "muted" }, t("backlog.empty")));
}

function storyRow(story) {
  return h("li", { class: "story-row", dataset: { id: story.id } },
    h("div", { class: "story-meta" },
      h("span", { class: "story-key" }, story.key),
      h("span", { class: `status status-${story.status}` }, t(`status.${story.status}`)),
      story.size ? h("span", { class: "size" }, story.size) : null,
      h("span", { class: "origin", title: t(`backlog.origin.${story.origin}`) }, story.origin === "ai" ? "AI" : "✎")),
    h("p", { class: "story-title" }, story.title));
}
