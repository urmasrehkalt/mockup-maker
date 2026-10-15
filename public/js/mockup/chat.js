// AI chat beside a mockup (#35): an instruction changes the mockup at once, as a new
// version, and the criteria of the linked stories follow. One step can be undone.

import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { errorText, notice } from "../ui.js";

/**
 * @param options { projectId, mockupId, getVersion() the newest version the viewer knows,
 *                  onApplied(mockup) after a change, onRefresh() after an undo or a stale refusal }
 * @returns { element, reload(), setEnabled(enabled) }
 */
export function mockupChat({ projectId, mockupId, getVersion, onApplied, onRefresh }) {
  let messages = [];
  let canUndo = false;
  let busy = false;
  let enabled = true;
  let problem = null;

  const history = h("div", { class: "mockup-chat-history", "aria-live": "polite" });
  const status = h("div", { class: "form-status" });
  const box = h("textarea", { rows: 2, maxlength: 1000, placeholder: t("mockup.chat_hint"),
    "aria-label": t("mockup.chat_title") });
  const send = h("button", { type: "submit", class: "primary" }, t("mockup.chat_send"));
  const old = h("p", { class: "hint" }, t("mockup.chat_old_version"));

  function draw() {
    box.disabled = busy || !enabled;
    send.disabled = busy || !enabled;
    old.hidden = enabled;
    mount(history, messages.map(row), busy ? h("p", { class: "mockup-chat-working" }, t("mockup.chat_working")) : null);
    mount(status, problem ? notice(problem, "error") : null);
    history.scrollTop = history.scrollHeight;
  }

  function row(message, index) {
    const mine = message.role === "user";
    const last = index === messages.length - 1;
    return h("div", { class: `mockup-chat-message ${mine ? "user" : "assistant"} ${message.undone ? "undone" : ""}` },
      h("div", { class: "message-author" }, mine ? t("mockup.chat_you") : t("mockup.chat_ai")),
      h("p", {}, message.text),
      mine ? null : h("p", { class: "hint" },
        message.version ? t("mockup.chat_version", { version: message.version }) : t("mockup.chat_unchanged"),
        message.story_keys.length ? ` · ${t("mockup.chat_stories", { keys: message.story_keys.join(", ") })}` : null,
        message.undone ? ` · ${t("mockup.chat_undone")}` : null),
      !mine && last && canUndo && !message.undone
        ? h("button", { type: "button", class: "small", onclick: undo }, `↶ ${t("mockup.chat_undo")}`) : null);
  }

  async function reload() {
    try {
      ({ messages, can_undo: canUndo } = await api.mockupChat(projectId, mockupId));
      problem = null;
    } catch (error) {
      problem = errorText(error);
    }
    draw();
  }

  async function submit() {
    const instruction = box.value.trim();
    if (!instruction || busy || !enabled) return;
    busy = true;
    problem = null;
    draw();
    try {
      const result = await api.instructMockup(projectId, mockupId, instruction, getVersion());
      messages = result.messages;
      canUndo = result.can_undo;
      box.value = "";
      busy = false;
      draw();
      await onApplied(result.mockup);
    } catch (error) {
      busy = false;
      if (error.code === "stale_version") {
        problem = errorText(error);
        draw();
        await onRefresh();
        await reload();
        return;
      }
      // The AI failed: nothing was changed or stored, the text stays for another try.
      problem = error.code?.startsWith("ai_") ? t("mockup.chat_failed") : errorText(error);
      draw();
    }
  }

  async function undo() {
    busy = true;
    draw();
    try {
      await api.undo(projectId);
      busy = false;
      await onRefresh();
      await reload();
    } catch (error) {
      busy = false;
      problem = errorText(error);
      draw();
    }
  }

  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  const element = h("section", { class: "mockup-chat", "aria-label": t("mockup.chat_title") },
    h("h3", {}, t("mockup.chat_title")),
    history, old, status,
    h("form", { class: "composer", onsubmit: (e) => { e.preventDefault(); submit(); } }, box, send));
  draw();
  reload();
  return { element, reload, setEnabled(value) { enabled = value; draw(); } };
}
