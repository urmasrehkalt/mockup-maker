// Story map: each role's happy path as a lane, stories left to right in backlog order,
// with the MVP line drawn where the role's first-version stories end.

import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { openStoryEditor } from "./story-editor.js";

export function openStoryMap(state, reload) {
  const dialog = h("dialog", { class: "editor story-map", "aria-label": t("storymap.title") });
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });

  // Roles in the order they first appear in the backlog, then confirmed roles without stories.
  const lanes = new Map();
  for (const story of state.stories) {
    if (!lanes.has(story.role_name)) lanes.set(story.role_name, []);
    lanes.get(story.role_name).push(story);
  }
  for (const role of state.roles) if (!lanes.has(role.name)) lanes.set(role.name, []);
  const hasLine = state.project.mvp_count !== null && state.project.mvp_count !== undefined;

  const card = (story, step) => h("li", {},
    h("button", { type: "button", class: `map-card status-${story.status} ${story.in_mvp ? "in-mvp" : ""}`,
      "aria-label": t("backlog.edit_story", { key: story.key }),
      onclick: () => { close(); openStoryEditor(state, story, reload); } },
      h("span", { class: "map-step" }, String(step)),
      h("span", { class: "story-meta" }, h("span", { class: "story-key" }, story.key),
        h("span", { class: `status status-${story.status}` }, t(`status.${story.status}`))),
      h("span", { class: "map-action" }, story.action)));

  const lane = ([role, stories]) => {
    const items = [];
    stories.forEach((story, i) => {
      if (hasLine && i > 0 && stories[i - 1].in_mvp && !story.in_mvp) {
        items.push(h("li", { class: "map-divider", "aria-label": t("storymap.mvp_divider") }, h("span", {}, t("storymap.mvp_divider"))));
      }
      items.push(card(story, i + 1));
    });
    return h("section", { class: "map-lane" },
      h("h3", {}, role, h("span", { class: "count" }, ` ${stories.length}`)),
      stories.length ? h("ol", { class: "map-row" }, items) : h("p", { class: "hint" }, t("storymap.no_stories")));
  };

  mount(dialog,
    h("div", { class: "viewer-head" },
      h("h2", {}, t("storymap.title")),
      h("button", { type: "button", class: "small", onclick: close }, t("mockup.close"))),
    h("p", { class: "hint" }, t(hasLine ? "storymap.hint_mvp" : "storymap.hint")),
    lanes.size ? [...lanes].map(lane) : h("p", { class: "muted" }, t("backlog.empty")));
  document.body.append(dialog);
  dialog.showModal();
}
