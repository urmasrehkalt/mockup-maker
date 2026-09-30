import { api } from "./api.js";
import { t } from "./i18n.js";
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

window.addEventListener("hashchange", route);
route();
showAiStatus();
