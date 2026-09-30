# Mockup Maker

Veebirakendus, mis aitab projektijuhil muuta kliendi umbmäärase idee juhitud vestluse
kaudu kasutajalugudeks, vastuvõtukriteeriumideks ja mockup'ideks. AI juhib protsessi,
inimene otsustab: ükski AI ettepanek ei jõua backlog'i ilma kasutaja kinnituseta.

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
| `AI_MODEL` | `gpt-6-astra` | Codexi mudel |
| `AI_REASONING` | `low` | `low`, `medium` või `high` |
| `AI_TIMEOUT` | `180` | sekundid enne Codexi protsessi katkestamist |
| `CODEX_BIN` | PATH-ist | Codex CLI absoluutne tee |
| `CODEX_HOME` | `~/.codex` | Codexi sisselogimise kaust |

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
ja seejärel näidatakse arusaadavat veateadet.

## Testid

```bash
.venv/bin/pytest
```

Testid ei vaja võrku, töötavat serverit ega päris võtmeid.
