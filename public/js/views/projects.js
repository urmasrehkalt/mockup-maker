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
    maxlength: 1000, rows: 2, placeholder: t("projects.description_hint") });
  const idea = h("textarea", { id: "project-idea", name: "idea", maxlength: 4000, rows: 4,
    placeholder: t("projects.idea_hint") });
  const template = h("select", { id: "project-template" });
  const removeTemplate = h("button", { type: "button", class: "small", hidden: true }, t("templates.delete"));
  const status = h("div", { class: "form-status" });
  const submit = h("button", { type: "submit", class: "primary" }, t("projects.create"));
  let templates = [];

  async function loadTemplates(selected = "") {
    templates = await api.projectTemplates().catch(() => []);
    mount(template, h("option", { value: "" }, t("templates.none")),
      h("optgroup", { label: t("templates.built_in") }, templates.filter((x) => x.built_in).map(option)),
      templates.some((x) => !x.built_in)
        ? h("optgroup", { label: t("templates.own") }, templates.filter((x) => !x.built_in).map(option)) : null);
    template.value = selected;
    removeTemplate.hidden = !selected.startsWith("u");
  }
  const option = (x) => h("option", { value: x.key }, x.name);

  template.addEventListener("change", () => {
    const chosen = templates.find((x) => x.key === template.value);
    removeTemplate.hidden = !chosen || chosen.built_in;
    if (!chosen) return;
    name.value = chosen.name;
    description.value = chosen.description;
    idea.value = chosen.idea;
    name.focus();
  });

  removeTemplate.addEventListener("click", async () => {
    const chosen = templates.find((x) => x.key === template.value);
    if (!chosen || !confirm(t("templates.confirm_delete", { name: chosen.name }))) return;
    try {
      await api.deleteProjectTemplate(chosen.key);
      await loadTemplates();
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
    }
  });

  async function saveTemplate() {
    mount(status);
    if (!name.value.trim() || !idea.value.trim()) {
      mount(status, notice(t("templates.need_name_and_idea"), "error"));
      return;
    }
    try {
      const saved = await api.saveProjectTemplate({ name: name.value, description: description.value, idea: idea.value });
      await loadTemplates(saved.key);
      mount(status, notice(t("templates.saved", { name: saved.name })));
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
    }
  }

  async function onSubmit(event) {
    event.preventDefault();
    submit.disabled = true;
    mount(status);
    try {
      const project = await api.createProject({ name: name.value, description: description.value, idea: idea.value });
      location.hash = `#/p/${project.id}`;
    } catch (error) {
      mount(status, notice(errorText(error), "error"));
      submit.disabled = false;
    }
  }

  loadTemplates();
  return h("form", { onsubmit: onSubmit },
    h("h2", {}, t("projects.new")),
    h("label", { for: "project-template" }, t("templates.start_from")),
    h("div", { class: "inline-form template-row" }, template, removeTemplate),
    h("label", { for: "project-name" }, t("projects.name")), name,
    h("label", { for: "project-description" }, t("projects.description")), description,
    h("label", { for: "project-idea" }, t("projects.idea")), idea,
    h("p", { class: "hint" }, t("projects.idea_note")),
    status, submit,
    h("button", { type: "button", class: "save-template", onclick: saveTemplate }, t("templates.save")));
}
