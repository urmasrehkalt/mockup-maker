// "Mockups" section of the story editor: linked mockups, create from a template, link or unlink.
// Changes apply at once (they are not part of the editor's Save) and can be undone.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { thumbnail } from "./render.js";
import { openMockupEditor } from "./editor.js";
import { openMockupViewer } from "./viewer.js";

let templateCache = null;

export function storyMockups(state, story, reload) {
  const section = h("fieldset", { class: "story-mockups" });
  if (!story) {
    mount(section, h("legend", {}, t("mockup.section")), h("p", { class: "hint" }, t("mockup.save_first")));
    return section;
  }
  draw(section, state, story, reload);
  return section;
}

async function draw(section, state, story, reload) {
  const linked = state.mockups.filter((m) => story.mockup_ids.includes(m.id));
  const others = state.mockups.filter((m) => !story.mockup_ids.includes(m.id));
  const status = h("div", { class: "form-status" });
  templateCache ??= await api.templates().catch(() => []);

  const act = async (work) => {
    mount(status);
    try {
      await work();
      const next = await reload();
      draw(section, next, next.stories.find((s) => s.id === story.id) ?? story, reload);
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
    }
  };

  const refresh = async () => {
    const next = await reload();
    draw(section, next, next.stories.find((s) => s.id === story.id) ?? story, reload);
  };
  const sharedWith = (m) => state.stories.filter((s) => s.mockup_ids.includes(m.id)).map((s) => s.key);
  const viewerOptions = { projectId: state.project.id, onChange: refresh };
  const templateSelect = h("select", { "aria-label": t("mockup.template") },
    templateCache.map((tpl) => h("option", { value: tpl.key }, tpl.name)));
  const existingSelect = h("select", { "aria-label": t("mockup.existing") },
    others.map((m) => h("option", { value: m.id }, `${m.title} (v${m.version})`)));

  mount(section,
    h("legend", {}, t("mockup.section")),
    linked.length
      ? h("ul", { class: "mockup-links" }, linked.map((m) => h("li", {},
        h("button", { type: "button", class: "thumb-button", onclick: () => openMockupViewer(m, { ...viewerOptions, sharedWith: sharedWith(m) }),
          "aria-label": t("mockup.open", { title: m.title }) }, thumbnail(m.tree)),
        h("div", { class: "mockup-link-body" },
          h("strong", {}, m.title), h("span", { class: "muted" }, ` · v${m.version}`),
          h("div", { class: "mockup-link-actions" },
            h("button", { type: "button", class: "small", onclick: () => openMockupViewer(m, { ...viewerOptions, sharedWith: sharedWith(m) }) }, t("mockup.view")),
            h("button", { type: "button", class: "small", onclick: () =>
              openMockupEditor(m, { projectId: state.project.id, sharedWith: sharedWith(m), onSaved: refresh }) },
            `✎ ${t("mockup.edit")}`),
            h("button", { type: "button", class: "small", onclick: () =>
              act(() => api.unlinkMockup(state.project.id, story.id, m.id)) }, t("mockup.unlink")))))))
      : h("p", { class: "hint" }, t("mockup.none")),
    h("div", { class: "inline-form" }, templateSelect,
      h("button", { type: "button", class: "small", onclick: () => act(() => api.createMockup(state.project.id,
        { template: templateSelect.value, story_id: story.id })) }, t("mockup.from_template"))),
    others.length ? h("div", { class: "inline-form" }, existingSelect,
      h("button", { type: "button", class: "small", onclick: () =>
        act(() => api.linkMockup(state.project.id, story.id, Number(existingSelect.value))) }, t("mockup.link"))) : null,
    status);
}
