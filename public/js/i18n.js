// UI strings. Estonian only for now; #20 adds English and a language switch.

const STRINGS = {
  et: {
    "ai.codex": "AI ühendatud",
    "ai.mock": "AI näidisrežiimis",
    "ai.off": "AI väljas",
    "ai.unknown": "Server ei vasta",

    "projects.title": "Projektid",
    "projects.empty": "Projekte veel pole. Loo esimene projekt, et alustada kliendiga kohtumist.",
    "projects.updated": "Muudetud {when}",
    "projects.new": "Uus projekt",
    "projects.name": "Nimi",
    "projects.name_hint": "nt Spordiklubi veeb",
    "projects.description": "Lühikirjeldus",
    "projects.description_hint": "Kellele ja milleks, ühe-kahe lausega (võib jätta tühjaks)",
    "projects.create": "Loo projekt",
    "projects.back": "Kõik projektid",

    "step.idea": "Idee",
    "step.roles": "Rollid",
    "step.stories": "Lood",
    "step.priorities": "Prioriteedid",
    "step.criteria": "Kriteeriumid ja mockup",
    "step.refinements": "Täpsustused",
    "step.grooming": "Groomimine",
    "steps.label": "Protsessi etapid",

    "resume.start": "Alustame. Kirjelda kliendi ideed oma sõnadega, ühe-kahe lausega. Kasutajalugude vormi pole vaja teada.",
    "resume.continue": "Tere tagasi! Jäime pooleli etapis „{step}“. Kuidas jätkame?",
    "action.continue_conversation": "Jätkame vestlust",
    "action.continue_roles": "Jätkame rollidega",
    "action.go_stories": "Liigume lugude juurde",
    "action.continue_stories": "Jätkame lugudega",
    "action.choose_priority": "Valime, millest alustada",
    "action.continue_criteria": "Jätkame kriteeriumide ja mockup'iga",
    "action.next_story": "Järgmine lugu",
    "action.enter_refinement": "Sisestan kliendi täpsustuse",
    "action.review_backlog": "Vaatame backlog'i üle",
    "action.end_meeting": "Lõpetame kohtumise",

    "chat.you": "Sina",
    "chat.assistant": "AI",

    "error.generic": "Midagi läks valesti. Proovi uuesti.",
    "error.not_found": "Projekti ei leitud.",
    "error.validation": "Kontrolli sisestatud andmeid.",
  },
};

let lang = "et";

export function t(key, params = {}) {
  const text = STRINGS[lang][key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? `{${name}}`);
}

export function formatDateTime(iso) {
  return new Intl.DateTimeFormat("et-EE", { dateStyle: "medium", timeStyle: "short" })
    .format(new Date(iso));
}
