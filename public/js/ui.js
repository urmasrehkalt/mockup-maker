import { h } from "./dom.js";
import { t } from "./i18n.js";

/** The Definition of Ready as a checklist: every condition, met or not. */
export function readinessList(story, missing = story?.readiness ?? []) {
  const byCode = new Map(missing.map((m) => [m.code, m]));
  const codes = ["connextra", "criteria_count", "criteria_testable", "mockup", "open_questions"];
  return h("ul", { class: "readiness" }, codes.map((code) => {
    const miss = byCode.get(code);
    const notApplicable = code === "mockup" && story && !story.needs_view;
    return h("li", { class: miss ? "missing" : "met" },
      h("span", { class: "mark", "aria-hidden": "true" }, miss ? "✗" : "✓"),
      t(`ready.${code}${notApplicable ? "_na" : miss ? "_missing" : ""}`, { count: miss?.count ?? 0 }));
  }));
}

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
