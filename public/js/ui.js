import { h } from "./dom.js";
import { t } from "./i18n.js";

export function errorText(error) {
  const key = `error.${error?.code}`;
  return t(key) === key ? t("error.generic") : t(key);
}

/** Testability warnings for one criterion, or null when it is fine. */
export function issueList(issues) {
  if (!issues?.length) return null;
  return h("ul", { class: "issues", role: "note" }, issues.map((issue) =>
    h("li", {}, `⚠ ${t(`issue.${issue.code}`)}`, issue.words.length ? h("span", { class: "issue-words" }, `: ${issue.words.join(", ")}`) : null)));
}

export function notice(text, kind = "info") {
  return h("p", { class: `notice ${kind}`, role: kind === "error" ? "alert" : "status" }, text);
}
