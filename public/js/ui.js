import { h } from "./dom.js";
import { t } from "./i18n.js";

export function errorText(error) {
  const key = `error.${error?.code}`;
  return t(key) === key ? t("error.generic") : t(key);
}

export function notice(text, kind = "info") {
  return h("p", { class: `notice ${kind}`, role: kind === "error" ? "alert" : "status" }, text);
}
