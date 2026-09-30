# Mockup Maker

Veebirakendus, mis aitab projektijuhil muuta kliendi umbmäärase idee juhitud vestluse
kaudu kasutajalugudeks, vastuvõtukriteeriumideks ja mockup'ideks. AI juhib protsessi,
inimene otsustab: ükski AI ettepanek ei jõua backlog'i ilma kasutaja kinnituseta.

## Dokumendid

- [Kasutusstsenaarium](docs/kasutusstsenaarium.md): kuidas projektijuht rakendust avakohtumisel ja backlog'i ülevaatusel kasutab
- [Arendustöö backlog](docs/arendusbacklog.md): rakenduse enda arendus kasutajalugudena, järjestuse põhjendus ja MVP joon
- [Ülevaade](docs/ulevaade.md): mis töötab, mis jäi pooleli ja millised on AI teadaolevad piirangud
- [Demo](docs/demo.md): 5–10 minuti demo käik

## Mida rakendus teeb

- **Projektid.** Projekt luuakse nime, kirjelduse ja sisu keelega, soovi korral mallist. Projekti avamisel jätkub töö samast kohast: vestlus, backlog, mockup'id ja protsessi etapp on alles.
- **Juhitud vestlus.** AI küsib täpsustavaid küsimusi valmis vastustega, pakub rollid, lood happy path'i järjekorras, soovitab põhjendusega, millest alustada, ning lõpetab iga vastuse järgmiste sammudega. Vabatekst on alati lubatud ja etappide riba näitab, kus protsess on.
- **Backlog.** Lood on Connextra kujul (roll, tegevus ja kasu eraldi), neil on kriteeriumid, staatus, suurus, avatud küsimused, mockup'id ja päritolu. Lugusid saab käsitsi lisada, muuta, lohistada ja kustutada ning viimaseid muudatusi tagasi võtta. Valmisoleku definitsioon on serveris jõustatud.
- **Uus vaade kirjeldusest.** Nupp „+ Uus vaade“ laseb vaadet sõnadega kirjeldada (soovi korral mallist lähtudes); AI koostab korraga Connextra loo, vastuvõtukriteeriumid ja mockup'i, mille saab enne backlog'i lisamist üle vaadata ja muuta.
- **Mockup'id.** Vaade on kindlatest komponentidest koosnev puu, mille rakendus ise joonistab (mitte AI-HTML). Kriteeriumid viitavad mockup'i elementidele, versioonid säilivad, mockup'i saab käsitsi redigeerida, sellele saab joonistada märkmeid ja selle saab alla laadida PNG-na.
- **Kliendi täpsustus.** AI koostab muudatusettepaneku, mida näeb enne rakendamist eelvaatena. Server tagab, et muutub ainult valitud lugu.
- **Groomimine.** Käsitsi jagamine, ühendamine, MVP joon ja alguspunkt ning AI ülevaatus, mille iga leiu saab rakendada, muuta või tähelepanuta jätta. Story map näitab iga rolli happy path'i eraldi real.
- **Eksport.** Backlog'i saab alla laadida Markdownina (lugemiseks ja jagamiseks) ja CSV-na (tabelarvutusse), mõlemad backlog'i järjekorras koos MVP joonega.
- **Agile Tracker.** Lood saab koos mockup'i piltidega saata [Agile Trackerisse](https://github.com/urmasrehkalt/agile-tracker); uuesti saatmine uuendab olemasolevat lugu.
- **Kaks keelt.** Liides on eesti ja inglise keeles, AI kirjutab projekti keeles.

## Ülesehitus

| Kaust / fail | Sisu |
| --- | --- |
| `app/main.py` | FastAPI rakendus, marsruudid ja staatilised failid |
| `app/config.py` | seaded keskkonnast ja `.env` failist |
| `app/ai/` | AI-kiht: Codexi ja näidispakkuja, skeemi koostamine ja vastuste kontroll koos kordusega |
| `app/conversation.py` | juhitud vestlus: üks samm ühe kasutaja sisendi kohta, reeglid ja AI juhised, uus vaade kirjeldusest |
| `app/backlog.py` | lood, kriteeriumid, tagasivõtmine, valmisoleku definitsioon, jagamine ja ühendamine |
| `app/mockups.py`, `app/mockup_templates.py`, `app/mockup_png.py` | mockup'i komponendid ja reeglid, mallid, versioonid, märkmed ja PNG |
| `app/review.py`, `app/testability.py` | AI ülevaatus ja kriteeriumide kontrollitavuse reegel |
| `app/tracker.py`, `app/templates.py`, `app/projects.py`, `app/db.py` | trackerisse saatmine, projektimallid, projektid ja andmebaas (SQLite, migratsioonid) |
| `app/export.py` | backlog'i eksport Markdowni ja CSV-sse |
| `public/` | liides: HTML, CSS ja JavaScripti moodulid ilma ehitussammuta |
| `tests/` | automaattestid (pytest); AI ja tracker on testides asendatud |
| `docs/` | esitamisdokumendid (vt [Dokumendid](#dokumendid)) |
| `start.sh` | virtuaalkeskkonna loomine ning serveri käivitamine ja peatamine |

## Turvalisus

- AI päringud käivad ainult serveri kaudu. Rakendus ei hoia API võtit: Codexi sisselogimine on serveri kasutaja `CODEX_HOME` kaustas, mis ei ole repositooriumis.
- Iga AI vastus kontrollitakse serveris skeemi ja reeglite järgi enne, kui see kasutajani jõuab.
- Mockup ei ole kunagi HTML: rakendus joonistab komponendipuu ise ja kogu tekst lisatakse tekstina, märkmed on SVG ilma HTML-ita. Seega ei saa mockup'i sisu brauseris koodi käivitada.
- Trackeri päringud teeb server, brauser trackeriga otse ei suhtle.
- Rakendusel **ei ole sisselogimist**: see on mõeldud ühe projektijuhi tööriistaks tema enda arvutis. Kui see pannakse avalikule aadressile, peab selle ette panema vähemalt parooli (näiteks Caddy `basic_auth`), sest muidu saaks igaüks kasutada serveri AI tellimust ja näha projekte.

## Tehnoloogiad

- Python 3.12, FastAPI, Pydantic v2
- Frontend: tavaline HTML/CSS/JS kaustas `public/`, ilma ehitussammuta
- Andmed: SQLite (`data/mockup-maker.db`)
- Testid: pytest + FastAPI TestClient

## Käivitamine

Eeldus: Python 3.12 (`python3.12`).

```bash
cp .env.example .env   # vajadusel muuda väärtusi
./start.sh             # loob .venv, installib sõltuvused, käivitab serveri
```

Rakendus avaneb aadressil <http://localhost:8010>.

| Käsk | Tegevus |
| --- | --- |
| `./start.sh` | käivitab serveri taustal (kui juba jookseb, siis taaskäivitab) |
| `./start.sh stop` | peatab serveri |
| `./start.sh status` | näitab, kas server jookseb |

Logid on failis `.uvicorn.log`. Teise Pythoni kasutamiseks: `PYTHON=/tee/pythonini ./start.sh`.

## Keskkonnamuutujad

Kõik muutujad on kirjeldatud failis [.env.example](.env.example). Protsessi keskkonnas
määratud väärtus on tähtsam kui `.env` failis olev.

| Muutuja | Vaikimisi | Tähendus |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test` või `production` |
| `DATABASE_PATH` | `data/mockup-maker.db` | SQLite faili asukoht |
| `PORT` | `8010` | port, mida `./start.sh` kasutab |
| `AI_PROVIDER` | `mock` | `codex` (ChatGPT tellimus Codex CLI kaudu), `mock` või `off` |
| `AI_MODEL` | `gpt-6-luna` | Codexi mudel |
| `AI_REASONING` | `medium` | `low`, `medium` või `high` |
| `AI_TIMEOUT` | `180` | sekundid enne Codexi protsessi katkestamist |
| `CODEX_BIN` | PATH-ist | Codex CLI absoluutne tee |
| `CODEX_HOME` | `~/.codex` | Codexi sisselogimise kaust |
| `TRACKER_URL` | tühi | Agile Trackeri API aadress serveri jaoks; tühjana saatmist ei pakuta |
| `TRACKER_PUBLIC_URL` | tühi | Trackeri aadress brauseris (linkideks) |
| `TRACKER_POINTS` | `S=2,M=5,L=8` | loo suurus → trackeri punktid |
| `TRACKER_TIMEOUT` | `10` | sekundid ühe trackeri päringu kohta |
| `MOCKUP_FONT`, `MOCKUP_FONT_BOLD` | süsteemi font | TrueType fondifailid mockup'i PNG ekspordi jaoks; vaikimisi DejaVu Sans (Linux) või Arial (macOS), nende puudumisel Pillow'ga kaasas olev font |

## AI ühendamine (ChatGPT tellimus)

AI päringud käivad ainult serveri kaudu: server käivitab kohaliku
[Codex CLI](https://github.com/openai/codex) (`codex exec`), mis on sisse logitud
ChatGPT tellimusega. API võtit rakendus ei vaja ega hoia; sisselogimise andmed jäävad
Codexi kausta (`CODEX_HOME`).

```bash
codex login --device-auth   # üks kord, kinnita kood brauseris
```

Seejärel pane `.env` faili `AI_PROVIDER=codex` ja taaskäivita server. Iga AI vastus
kontrollitakse serveris skeemi järgi; vigase vastuse korral proovitakse üks kord uuesti
ja seejärel näidatakse arusaadavat veateadet. Vaikimisi mudel on `gpt-6-luna` keskmise
mõtlemistasemega; valiku põhjendus (kolme mudeli võrdlus) on [ülevaates](docs/ulevaade.md#mudeli-valik).

## Keeled

Liidese keelt (eesti / inglise) saab vahetada päise nupust; valik jääb brauserisse meelde.
Igal projektil on oma **sisu keel**, mis valitakse projekti loomisel: selles keeles kirjutab AI
lood, kriteeriumid ja mockup'id ning selles vormis koostatakse Connextra pealkiri
(„Külastajana soovin …, et …“ või „As a visitor, I want to …, so that …“). Nii jääb üks backlog
ühte keelde ka siis, kui liidese keelt vahetatakse. Näidisrežiimi (`AI_PROVIDER=mock`) vastused on
ainult eesti keeles.

## Testid

```bash
.venv/bin/pytest
```

Testid ei vaja võrku, töötavat serverit ega päris võtmeid: AI ja Agile Tracker on testides
asendatud. Andmebaas luuakse iga testi jaoks eraldi ajutisse kausta ning arendaja `.env` faili
AI ja trackeri seaded testidesse ei jõua.
