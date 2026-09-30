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

## Testid

```bash
.venv/bin/pytest
```

Testid ei vaja võrku, töötavat serverit ega päris võtmeid.
