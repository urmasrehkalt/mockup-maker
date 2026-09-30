"""Page templates: starting points for a mockup, built from the component library.

Each is a plain component tree (validated as `mockups.Tree` when served), with
stable ids so criteria written against a template keep pointing at the same
elements after it is edited.
"""

HEADER = {"id": "header", "type": "header", "text": "Teenuse nimi", "children": [
    {"id": "nav", "type": "nav", "items": ["Avaleht", "Teenused", "Hinnad", "Kontakt"]},
    {"id": "login", "type": "button", "text": "Logi sisse", "variant": "secondary"},
]}
FOOTER = {"id": "footer", "type": "footer", "text": "© Ettevõte · info@example.com · +372 5555 5555"}

TEMPLATES: dict[str, tuple[str, dict]] = {
    "landing": ("Avaleht", {"title": "Avaleht", "components": [
        HEADER,
        {"id": "hero", "type": "section", "children": [
            {"id": "hero-title", "type": "heading", "level": 1, "text": "Peamine pakkumine ühe lausega"},
            {"id": "hero-text", "type": "text", "text": "Lühike selgitus, kellele teenus on ja mis kasu see toob."},
            {"id": "hero-cta", "type": "button", "text": "Alusta", "variant": "primary"},
        ]},
        {"id": "hero-image", "type": "image", "text": "Pilt teenusest"},
        {"id": "features", "type": "grid", "columns": 3, "children": [
            {"id": "feature-1", "type": "card", "text": "Eelis 1", "secondary": "Lühike kirjeldus."},
            {"id": "feature-2", "type": "card", "text": "Eelis 2", "secondary": "Lühike kirjeldus."},
            {"id": "feature-3", "type": "card", "text": "Eelis 3", "secondary": "Lühike kirjeldus."},
        ]},
        FOOTER,
    ]}),
    "list": ("Loend", {"title": "Loend", "components": [
        HEADER,
        {"id": "list-title", "type": "heading", "level": 1, "text": "Kõik kirjed"},
        {"id": "filters", "type": "form", "children": [
            {"id": "search", "type": "input", "text": "Otsi", "variant": "text", "secondary": "Sisesta märksõna"},
            {"id": "category", "type": "input", "text": "Kategooria", "variant": "select"},
        ]},
        {"id": "results", "type": "grid", "columns": 3, "children": [
            {"id": "item-1", "type": "card", "text": "Kirje 1", "secondary": "Lühikirjeldus", "children": [
                {"id": "item-1-open", "type": "button", "text": "Vaata", "variant": "link"}]},
            {"id": "item-2", "type": "card", "text": "Kirje 2", "secondary": "Lühikirjeldus", "children": [
                {"id": "item-2-open", "type": "button", "text": "Vaata", "variant": "link"}]},
            {"id": "item-3", "type": "card", "text": "Kirje 3", "secondary": "Lühikirjeldus", "children": [
                {"id": "item-3-open", "type": "button", "text": "Vaata", "variant": "link"}]},
        ]},
        FOOTER,
    ]}),
    "pricing": ("Hinnakiri", {"title": "Hinnakiri", "components": [
        HEADER,
        {"id": "pricing-title", "type": "heading", "level": 1, "text": "Paketid ja hinnad"},
        {"id": "packages", "type": "grid", "columns": 3, "children": [
            {"id": "package-basic", "type": "price_card", "text": "Põhipakett", "secondary": "29 € / kuu",
             "items": ["Omadus 1", "Omadus 2"], "children": [
                 {"id": "package-basic-choose", "type": "button", "text": "Vali", "variant": "primary"}]},
            {"id": "package-plus", "type": "price_card", "text": "Pluss", "secondary": "39 € / kuu",
             "items": ["Omadus 1", "Omadus 2", "Omadus 3"], "children": [
                 {"id": "package-plus-choose", "type": "button", "text": "Vali", "variant": "primary"}]},
            {"id": "package-premium", "type": "price_card", "text": "Premium", "secondary": "59 € / kuu",
             "items": ["Kõik omadused"], "children": [
                 {"id": "package-premium-choose", "type": "button", "text": "Vali", "variant": "primary"}]},
        ]},
        FOOTER,
    ]}),
    "detail": ("Detailvaade", {"title": "Detailvaade", "components": [
        HEADER,
        {"id": "detail-title", "type": "heading", "level": 1, "text": "Kirje nimi"},
        {"id": "detail-image", "type": "image", "text": "Kirje pilt"},
        {"id": "detail-text", "type": "text", "text": "Kirje põhjalik kirjeldus."},
        {"id": "detail-facts", "type": "table", "items": ["Omadus", "Väärtus"],
         "rows": [["Kestus", "60 min"], ["Asukoht", "Saal 1"]]},
        {"id": "detail-cta", "type": "button", "text": "Vali see", "variant": "primary"},
        FOOTER,
    ]}),
    "form": ("Vorm", {"title": "Vorm", "components": [
        HEADER,
        {"id": "form-title", "type": "heading", "level": 1, "text": "Registreerumine"},
        {"id": "form", "type": "form", "children": [
            {"id": "name", "type": "input", "text": "Nimi", "variant": "text", "required": True},
            {"id": "email", "type": "input", "text": "E-post", "variant": "email", "required": True},
            {"id": "phone", "type": "input", "text": "Telefon", "variant": "text"},
            {"id": "terms", "type": "input", "text": "Nõustun tingimustega", "variant": "checkbox",
             "required": True},
            {"id": "submit", "type": "button", "text": "Saada", "variant": "primary"},
        ]},
        FOOTER,
    ]}),
    "checkout": ("Maksmine", {"title": "Maksmine", "components": [
        HEADER,
        {"id": "checkout-steps", "type": "steps", "items": ["Valik", "Andmed", "Makse", "Kinnitus"]},
        {"id": "checkout-title", "type": "heading", "level": 1, "text": "Tellimuse kokkuvõte"},
        {"id": "order", "type": "table", "items": ["Toode", "Hind"],
         "rows": [["Valitud pakett", "29 €"], ["Kokku", "29 €"]]},
        {"id": "vat-note", "type": "note", "text": "Hinnad sisaldavad käibemaksu"},
        {"id": "payment", "type": "form", "children": [
            {"id": "method", "type": "input", "text": "Makseviis", "variant": "select"},
            {"id": "pay", "type": "button", "text": "Maksa", "variant": "primary"},
        ]},
        FOOTER,
    ]}),
    "confirmation": ("Kinnitus", {"title": "Kinnitus", "components": [
        HEADER,
        {"id": "success", "type": "notice", "variant": "success", "text": "Aitäh! Tellimus on kinnitatud."},
        {"id": "summary", "type": "list", "items": ["Tellimuse number: 12345", "Kinnitus saadeti e-postile"]},
        {"id": "next", "type": "button", "text": "Tagasi avalehele", "variant": "secondary"},
        FOOTER,
    ]}),
}
