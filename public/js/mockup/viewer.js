// Mockup viewer: a large preview with a desktop / mobile toggle and, for a saved
// mockup, its version history (preview any version, restore an earlier one).

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { formatDateTime, t } from "../i18n.js";
import { errorText, notice } from "../ui.js";
import { createArtboard } from "./annotations.js";
import { openMockupEditor } from "./editor.js";
import { renderTree } from "./render.js";

/**
 * @param mockup   { id?, title, version, tree }
 * @param options  { projectId, onChange, sharedWith } to show versions and allow editing;
 *                 onChange() runs after a restore or a saved edit
 */
export function openMockupViewer(mockup, { projectId = null, onChange = null, sharedWith = [] } = {}) {
  const stage = h("div", { class: "wf-stage" });
  const side = h("aside", { class: "versions" });
  const heading = h("h2", {});
  let viewport = "desktop";
  let shown = { number: mockup.version, tree: mockup.tree, annotations: mockup.annotations ?? [] };
  let annotating = false;
  let latest = mockup.version;

  const toggles = ["desktop", "mobile"].map((v) => h("button", {
    type: "button", class: "small", "aria-pressed": String(v === viewport),
    onclick: () => { viewport = v; draw(); },
  }, t(`mockup.${v}`)));

  const download = projectId && mockup.id ? h("a", { class: "button-link small", download: "" }, t("mockup.download")) : null;

  const markButton = projectId && mockup.id ? h("button", { type: "button", class: "small",
    onclick: () => { annotating = true; viewport = "desktop"; draw(); } }, `✎ ${t("marks.button")}`) : null;

  function draw() {
    if (download) download.href = `/api/projects/${projectId}/mockups/${mockup.id}/png?version=${shown.number}`;
    if (markButton) markButton.disabled = annotating || shown.number !== latest;
    toggles.forEach((b, i) => b.setAttribute("aria-pressed", String(["desktop", "mobile"][i] === viewport)));
    mount(heading, shown.tree.title, h("span", { class: "muted" }, ` · v${shown.number}`),
      shown.number !== latest ? h("span", { class: "old-version" }, t("mockup.older")) : null);
    if (annotating) {
      mount(stage, createArtboard(shown.tree, shown.annotations, { editable: true,
        onCancel: () => { annotating = false; draw(); },
        onSave: async (marks) => {
          try {
            const saved = await api.saveAnnotations(projectId, mockup.id, marks);
            shown = { number: saved.version, tree: saved.tree, annotations: saved.annotations };
            latest = saved.version;
            annotating = false;
            await onChange?.();
            await loadVersions();
            draw();
          } catch (error) {
            stage.prepend(notice(errorText(error), "error"));
          }
        } }).element);
    } else if (viewport === "desktop") {
      mount(stage, createArtboard(shown.tree, shown.annotations).element);
    } else {
      mount(stage, shown.annotations.length ? h("p", { class: "hint" }, t("marks.desktop_only")) : null,
        renderTree(shown.tree, { viewport }));
    }
  }

  async function loadVersions() {
    let list;
    try {
      list = await api.mockupVersions(projectId, mockup.id);
    } catch (error) {
      mount(side, notice(errorText(error), "error"));
      return;
    }
    latest = list.at(-1).number;
    const status = h("div", { class: "form-status" });
    mount(side,
      h("h3", {}, t("mockup.versions")),
      h("ol", { class: "version-list", reversed: true }, [...list].reverse().map((v) => h("li", {},
        h("button", { type: "button", class: `version ${v.number === shown.number ? "shown" : ""}`,
          "aria-pressed": String(v.number === shown.number),
          onclick: () => { shown = v; draw(); loadVersions(); } },
          h("strong", {}, `v${v.number}`), " ", noteLabel(v.note),
          h("span", { class: "muted version-date" }, formatDateTime(v.created_at)))))),
      shown.number !== latest ? h("button", { type: "button", class: "primary", onclick: async () => {
        try {
          const restored = await api.restoreVersion(projectId, mockup.id, shown.number);
          shown = { number: restored.version, tree: restored.tree };
          await onChange?.();
          await loadVersions();
          draw();
        } catch (error) {
          mount(status, notice(errorText(error), "error"));
        }
      } }, t("mockup.restore", { version: shown.number })) : null,
      status);
  }

  const dialog = h("dialog", { class: `editor viewer ${projectId ? "with-versions" : ""}`, "aria-label": mockup.title });
  const close = () => { dialog.close(); dialog.remove(); };
  mount(dialog,
    h("div", { class: "viewer-head" }, heading,
      h("div", { class: "segmented" }, toggles),
      download,
      markButton,
      projectId && mockup.id ? h("button", { type: "button", class: "small", onclick: () => {
        close();
        openMockupEditor({ ...mockup, tree: shown.tree }, { projectId, sharedWith, onSaved: onChange });
      } }, `✎ ${t("mockup.edit")}`) : null,
      h("button", { type: "button", class: "small", onclick: close }, t("mockup.close"))),
    h("div", { class: "viewer-body" }, stage, projectId && mockup.id ? side : null));
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dialog);
  draw();
  if (projectId && mockup.id) loadVersions();
  dialog.showModal();
}

// Where a version came from, from the note the server stored with it.
function noteLabel(note) {
  const [kind, detail] = note.split(":");
  switch (kind) {
    case "template": return t("mockup.note_template");
    case "proposal": return t("mockup.note_proposal");
    case "change": return t("mockup.note_change");
    case "restore": return t("mockup.note_restore", { version: detail });
    default: return t("mockup.note_manual");
  }
}
