// "Send to tracker" dialog: choose stories, push them to the Agile Tracker, show what happened.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { frameOn } from "../mockup/frame.js";
import { errorText, notice } from "../ui.js";

let status = null;

/** Whether the server has a tracker configured (asked once per page load). */
export async function trackerStatus() {
  status ??= await api.trackerStatus().catch(() => ({ configured: false }));
  return status;
}

export function openTrackerDialog(state, reload) {
  const dialog = h("dialog", { class: "editor tracker", "aria-label": t("tracker.title") });
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  const boxes = new Map();
  const results = h("div", { class: "form-status" });
  const send = h("button", { type: "button", class: "primary" }, t("tracker.send"));

  const rows = state.stories.map((story) => {
    const box = h("input", { type: "checkbox", checked: story.criteria.length > 0, disabled: !story.criteria.length });
    boxes.set(story.id, box);
    return h("li", {}, h("label", { class: "check" }, box,
      h("span", {}, h("strong", {}, story.key), " ", story.title,
        story.tracker_id ? h("span", { class: "hint" }, ` · ${t("tracker.already", { id: story.tracker_id })}`) : null,
        !story.criteria.length ? h("span", { class: "hint" }, ` · ${t("tracker.no_criteria")}`) : null)));
  });

  send.addEventListener("click", async () => {
    const ids = [...boxes].filter(([, box]) => box.checked).map(([id]) => id);
    if (!ids.length) return;
    send.disabled = true;
    mount(results, h("p", { class: "muted" }, t("tracker.sending")));
    try {
      const report = await api.pushToTracker(state.project.id, ids, frameOn());
      mount(results, h("ul", { class: "push-results" }, report.results.map((r) => h("li", { class: r.outcome },
        h("strong", {}, r.key), " ", t(`tracker.${r.outcome}`, { id: r.tracker_id }),
        r.mockup !== "none" ? h("span", { class: "hint" }, ` · ${t(`tracker.mockup_${r.mockup}`)}`) : null,
        r.message ? h("div", { class: "hint" }, r.message) : null))),
      status?.public_url ? h("p", {}, h("a", { href: status.public_url, target: "_blank", rel: "noopener" }, t("tracker.open"))) : null);
      await reload();
    } catch (error) {
      mount(results, notice(error.details?.message ?? errorText(error), "error"));
    }
    send.disabled = false;
  });

  mount(dialog,
    h("h2", {}, t("tracker.title")),
    h("p", { class: "hint" }, t("tracker.explain"), " ", t(frameOn() ? "tracker.framed" : "tracker.unframed")),
    h("ul", { class: "push-list" }, rows),
    results,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", onclick: close }, t("mockup.close")), send));
  document.body.append(dialog);
  dialog.showModal();
}
