// Device frames: a browser window around the desktop view, a phone around the
// mobile one. They are presentation only (not part of the mockup) and drawn
// in the page's own markup, marked aria-hidden. Whether they show is the
// viewer's choice, remembered in this browser and on by default.

import { h } from "../dom.js";
import { t } from "../i18n.js";

const KEY = "mockup-frame";

export function frameOn() {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

function setFrameOn(on) {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // Not remembered, still switched for this dialog.
  }
}

/** The toggle button; onChange(on) redraws whatever it frames. */
export function frameToggle(onChange) {
  const button = h("button", { type: "button", class: "small", title: t("mockup.frame_hint"),
    "aria-pressed": String(frameOn()),
    onclick: () => {
      const on = !frameOn();
      setFrameOn(on);
      button.setAttribute("aria-pressed", String(on));
      onChange(on);
    } }, t("mockup.frame"));
  return h("div", { class: "segmented" }, button);
}

/** Same rule as site_address() in app/mockup_png.py, e.g. "e-pood.ee/e-poe-avaleht". */
export function siteAddress(projectName, title, language = "et") {
  const slug = (text) => (text ?? "").normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const host = `${slug(projectName) || "example"}.${language === "en" ? "com" : "ee"}`;
  const path = slug(title);
  return path ? `${host}/${path}` : host;
}

export function browserFrame(content, address) {
  return h("div", { class: "device device-browser" },
    h("div", { class: "browser-bar", "aria-hidden": "true" },
      h("span", { class: "browser-dots" }, h("span"), h("span"), h("span")),
      h("span", { class: "browser-address" }, address)),
    h("div", { class: "device-screen" }, content));
}

/**
 * A phone at real size (375 × 812 screen). Once in a dialog, it is zoomed out to fit the
 * window, so it keeps a phone's proportions instead of being cut shorter.
 */
export function phoneFrame(content) {
  const phone = h("div", { class: "device device-phone" },
    h("div", { class: "phone-status", "aria-hidden": "true" },
      h("span", {}, "9:41"), h("span", { class: "phone-notch" }),
      h("span", { class: "phone-icons" }, h("span", { class: "phone-signal" }), h("span", { class: "phone-battery" }))),
    h("div", { class: "device-screen" }, content),
    h("div", { class: "phone-home", "aria-hidden": "true" }));
  const fit = () => {
    const dialog = phone.closest("dialog");
    if (!phone.isConnected || !dialog) {
      removeEventListener("resize", fit);
      return;
    }
    phone.style.zoom = "";
    const full = phone.offsetHeight;
    const around = dialog.scrollHeight - full;  // the dialog's heading, padding and stage
    const room = innerHeight - 38 - around;  // a modal dialog is at most 100% - 2em - 6px tall
    const k = Math.min(1, room / full, (phone.parentElement.clientWidth - 32) / phone.offsetWidth);
    phone.style.zoom = String(Math.max(0.45, k));
  };
  addEventListener("resize", fit);
  requestAnimationFrame(fit);
  return phone;
}
