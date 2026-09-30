import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { formatDateTime, t } from "../i18n.js";
import { errorText, notice } from "../ui.js";

export async function renderProjects(view) {
  const list = h("div", { class: "project-list", "aria-busy": "true" });
  mount(view, h("div", { class: "projects-page" },
    h("section", { class: "projects-main" }, h("h1", {}, t("projects.title")), list),
    h("aside", { class: "card new-project" }, createForm())));

  try {
    const projects = await api.listProjects();
    mount(list, projects.length ? projects.map(projectCard) : notice(t("projects.empty")));
  } catch (error) {
    mount(list, notice(errorText(error), "error"));
  }
  list.removeAttribute("aria-busy");
}

function projectCard(project) {
  return h("a", { class: "card project-card", href: `#/p/${project.id}` },
    h("h2", {}, project.name),
    project.description ? h("p", { class: "muted" }, project.description) : null,
    h("div", { class: "meta" },
      h("span", { class: "step-tag" }, t(`step.${project.step}`)),
      h("span", {}, t("projects.updated", { when: formatDateTime(project.updated_at) }))));
}

function createForm() {
  const name = h("input", { id: "project-name", name: "name", required: true, maxlength: 120,
    placeholder: t("projects.name_hint"), autocomplete: "off" });
  const description = h("textarea", { id: "project-description", name: "description",
    maxlength: 1000, rows: 3, placeholder: t("projects.description_hint") });
  const status = h("div", { class: "form-status" });
  const submit = h("button", { type: "submit", class: "primary" }, t("projects.create"));

  async function onSubmit(event) {
    event.preventDefault();
    submit.disabled = true;
    mount(status);
    try {
      const project = await api.createProject({ name: name.value, description: description.value });
      location.hash = `#/p/${project.id}`;
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
      submit.disabled = false;
    }
  }

  return h("form", { onsubmit: onSubmit },
    h("h2", {}, t("projects.new")),
    h("label", { for: "project-name" }, t("projects.name")), name,
    h("label", { for: "project-description" }, t("projects.description")), description,
    status, submit);
}
