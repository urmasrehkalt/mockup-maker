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


# English wording for the templates' sample texts (the structure and ids are shared).
ENGLISH = {
    "Avaleht": "Home", "Teenuse nimi": "Service name", "Teenused": "Services", "Hinnad": "Prices",
    "Kontakt": "Contact", "Logi sisse": "Log in", "Peamine pakkumine ühe lausega": "The main offer in one sentence",
    "Lühike selgitus, kellele teenus on ja mis kasu see toob.": "A short note on who the service is for and how it helps.",
    "Alusta": "Get started", "Pilt teenusest": "Picture of the service", "Eelis 1": "Benefit 1",
    "Lühike kirjeldus.": "Short description.", "Eelis 2": "Benefit 2", "Eelis 3": "Benefit 3",
    "© Ettevõte · info@example.com · +372 5555 5555": "© Company · info@example.com · +372 5555 5555",
    "Loend": "List", "Kõik kirjed": "All items", "Otsi": "Search", "Sisesta märksõna": "Enter a keyword",
    "Kategooria": "Category", "Kirje 1": "Item 1", "Lühikirjeldus": "Summary", "Vaata": "View",
    "Kirje 2": "Item 2", "Kirje 3": "Item 3", "Hinnakiri": "Pricing", "Paketid ja hinnad": "Packages and prices",
    "Põhipakett": "Basic", "29 € / kuu": "€29 / month", "Omadus 1": "Feature 1", "Omadus 2": "Feature 2",
    "Vali": "Choose", "Pluss": "Plus", "39 € / kuu": "€39 / month", "Omadus 3": "Feature 3", "Premium": "Premium",
    "59 € / kuu": "€59 / month", "Kõik omadused": "All features", "Detailvaade": "Detail", "Kirje nimi": "Item name",
    "Kirje pilt": "Item picture", "Kirje põhjalik kirjeldus.": "A full description of the item.",
    "Omadus": "Property", "Väärtus": "Value", "Kestus": "Duration", "60 min": "60 min", "Asukoht": "Location",
    "Saal 1": "Room 1", "Vali see": "Choose this", "Vorm": "Form", "Registreerumine": "Sign up", "Nimi": "Name",
    "E-post": "Email", "Telefon": "Phone", "Nõustun tingimustega": "I accept the terms", "Saada": "Send",
    "Maksmine": "Checkout", "Valik": "Choice", "Andmed": "Details", "Makse": "Payment", "Kinnitus": "Confirmation",
    "Tellimuse kokkuvõte": "Order summary", "Toode": "Product", "Hind": "Price", "Valitud pakett": "Selected package",
    "29 €": "€29", "Kokku": "Total", "Hinnad sisaldavad käibemaksu": "Prices include VAT", "Makseviis": "Payment method",
    "Maksa": "Pay", "Aitäh! Tellimus on kinnitatud.": "Thank you! Your order is confirmed.",
    "Tellimuse number: 12345": "Order number: 12345", "Kinnitus saadeti e-postile": "A confirmation was sent by email",
    "Tagasi avalehele": "Back to home",
}


def localized(key: str, language: str) -> tuple[str, dict]:
    """A template's name and tree in the project's language (Estonian as written)."""
    name, tree = TEMPLATES[key]
    if language != "en":
        return name, tree

    def tr(value):
        if isinstance(value, str):
            return ENGLISH.get(value, value)
        if isinstance(value, list):
            return [tr(v) for v in value]
        if isinstance(value, dict):
            return {k: (v if k in ("id", "type", "variant") else tr(v)) for k, v in value.items()}
        return value
    return tr(name), tr(tree)
