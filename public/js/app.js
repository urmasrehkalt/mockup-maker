import { api } from "./api.js";
import { getLang, setLang, t } from "./i18n.js";
import { renderProject } from "./views/project.js";
import { renderProjects } from "./views/projects.js";

const view = document.getElementById("view");

function route() {
  const match = location.hash.match(/^#\/p\/(\d+)$/);
  if (match) {
    renderProject(view, Number(match[1]));
  } else {
    renderProjects(view);
  }
  window.scrollTo(0, 0);
}

async function showAiStatus() {
  const pill = document.getElementById("ai-status");
  try {
    const { provider } = await api.aiStatus();
    pill.textContent = t(`ai.${provider}`);
    pill.dataset.state = provider;
  } catch {
    pill.textContent = t("ai.unknown");
    pill.dataset.state = "error";
  }
}

// The interface language switch: remembered in this browser, applied by redrawing.
const langSwitch = document.getElementById("lang-switch");
function showLangSwitch() {
  langSwitch.textContent = t("lang.switch");
  langSwitch.lang = getLang() === "et" ? "en" : "et";
}
langSwitch.addEventListener("click", () => {
  setLang(getLang() === "et" ? "en" : "et");
  showLangSwitch();
  showAiStatus();
  route();
});

window.addEventListener("hashchange", route);
showLangSwitch();
route();
showAiStatus();
