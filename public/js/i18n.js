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
    "resume.continue": "Oleme etapis „{step}“. Kuidas jätkame?",
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
    "chat.thinking": "AI mõtleb…",
    "chat.send": "Saada",
    "chat.idea_hint": "nt Spordiklubi tahab veebi, kus saab treeningutega tutvuda ja liikmeks astuda.",
    "chat.free_hint": "Kirjuta vabalt: vastus, täpsustus või küsimus",
    "chat.skipped": "Jätsin vahele",
    "chat.not_answered": "Vastamata",
    "chat.multi_hint": "(võid valida mitu)",
    "chat.confirm_choice": "Kinnita valik",
    "chat.other": "Muu (kirjutan ise)",
    "chat.other_hint": "Kirjuta oma vastus",
    "chat.skip": "Jäta vahele",
    "chat.roles_title": "Kasutajarollid",
    "chat.roles_none": "Vali vähemalt üks roll.",
    "chat.add_role": "Lisa roll",
    "chat.add_role_hint": "Uue rolli nimi",
    "chat.confirm_roles": "Kinnita rollid",
    "chat.retry": "Proovi uuesti",
    "chat.no_answer": "AI ei vastanud sinu viimasele sisendile. Sinu valik on salvestatud.",

    "error.generic": "Midagi läks valesti. Proovi uuesti.",
    "error.ai_disabled": "AI on selles serveris välja lülitatud. Sinu valik on salvestatud; saad jätkata käsitsi.",
    "error.ai_unavailable": "AI teenus ei ole praegu kättesaadav. Sinu valik on salvestatud.",
    "error.ai_timeout": "AI ei vastanud õigeaegselt. Sinu valik on salvestatud.",
    "error.ai_invalid_answer": "AI vastus oli vigane ka teisel katsel. Sinu valik on salvestatud.",
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
