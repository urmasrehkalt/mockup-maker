# Ülevaade

## Mis töötab

Kõik ülesande põhifunktsioonid on olemas ja kasutatavad nii ChatGPT tellimusega (Codex CLI kaudu) kui ka ilma AI-ta, kui töö käib käsitsi.

| Nõue | Seis | Kus |
| --- | --- | --- |
| Projektid, jätkamine samast kohast, püsivus | töötab | #3 |
| Juhitud vestlus: täpsustavad küsimused valikutega, rollid, lood happy path'i järjekorras, prioriteedi soovitus, järgmised sammud, etappide riba, vabatekst | töötab | #4, #5, #7 |
| AI arvestab projekti tegeliku seisuga (backlog, rollid, vastused, käsitsi muudatused) | töötab | #4, #5 |
| Struktureeritud vastused, serveri kontroll, kordus ja arusaadav veateade | töötab | #2 |
| Backlog: väljad, käsitsi haldus, lohistamine, tagasivõtmine, MVP joon | töötab | #6, #14 |
| Valmisoleku definitsioon, „Vajab täpsustamist“ koos avatud küsimusega | töötab | #13 |
| Mockup ja kriteeriumid, kooskõla (kriteerium viitab mockup'i elemendile) | töötab | #8, #9 |
| Uue vaate kirjeldamine promptiga: mockup, Connextra lugu ja kriteeriumid korraga | töötab | #27 |
| Kliendi täpsustus eelvaatega, ainult valitud loo muutmine, teised lood eraldi ettepanekutena | töötab | #11 |
| Mockup'i versioonid ja taastamine | töötab | #12 |
| Kontrollitavuse reegel (hinnangulised sõnad, mitu tingimust, ebamäärasus) | töötab | #10 |
| Groomimine: jagamine, ühendamine, AI ülevaatus leidudega „Rakenda“, „Muuda“, „Ignoreeri“ | töötab | #14, #15 |
| Turvalisus: AI ainult serveri kaudu, võtit pole repositooriumis, mockup ei käivita koodi | töötab | #2, #8, #18 |

Ülesande lisavõimalustest on tehtud backlog'i eksport Markdowni ja CSV-sse (#22), kriteeriumi ja mockup'i elemendi seos (kriteeriumile osutades tõstetakse element esile, #9), rollide kaupa story map (#22) ning mockup'i PNG eksport ja saatmine Agile Trackerisse (#16). Lisaks on käsitsi mockup'i redaktor (#17), vabakäe märkmed mockup'il (#18), projektimallid (#19), eesti- ning ingliskeelne liides (#20), mockup'i brauseri- või telefoniraam, mida saab sisse ja välja lülitada (#29), ning AI vestlus mockup'i juures, mis muudab mockup'it käsu järgi ja hoiab lood kooskõlas (#35), vestluse järjekord, mis lubab anda järgmise käsu enne eelmise lõppu (#36), ning kliendi mõtete liigitamine ja ideede nimekiri (#37).

### Kuidas seda kontrolliti

- **Automaattestid:** 265 testi (`.venv/bin/pytest`), mis katavad iga loo kriteeriumid. AI ja tracker on testides asendatud, nii et testid ei vaja võrku ega sisselogimist.
- **Brauser:** iga loo lõpus kontrolliti töövoogu Playwrightiga päris brauseris (laua- ja telefonilaius, hele ja tume teema).
- **Päris AI:** iga AI-ga seotud loo lõpus käis sama töövoog läbi reaalse Codexiga ning selle käigus leitud probleemid parandati enne loo lõpetamist (vt allpool).
- **Vastuvõtukatse:** ülesande vastuvõtukatse sammud käidi läbi päris Codexiga eraldi andmebaasiga (tulemus allpool).

### Vastuvõtukatse

Vastuvõtukatse käidi 30. septembril 2026 läbi päris Codexiga (esimene katse mudeliga `gpt-6-astra`, madal mõtlemistase), eraldi andmebaasi ja serveriga. Brauserit juhtis Playwright ja tegevused olid samad, mida õpetaja teeks: peamiselt klõpsud, kirjutati ainult idee, ühe kriteeriumi muudatus ja kliendi täpsustus. Kõik sammud läbisid, brauseri konsoolis ega serveri logis vigu polnud.

| Samm | Tulemus | AI aeg |
| --- | --- | --- |
| 1. Uus projekt ja üks ähmane lause, AI küsib täpsustava küsimuse | küsimus „Kui kaugele peaks külastaja saama veebis liikmeks astumisega minna?“ kolme vastusevariandiga ning „Muu“ ja „Jäta vahele“ | 13 s |
| 2. Vähemalt viis lugu happy path'i järjekorras, valitud lood backlog'i | 6 lugu treeningute sirvimisest liitumissoovi kinnituseni; 5 valitud lugu lisati klõpsudega | 23 s |
| 3. Soovitus, millest alustada, ja järjekorra muutmine | soovitus US-5 koos põhjendusega; järjekord muudeti noolenupuga | 16 s |
| 4. Kriteeriumid ja mockup; osa kinnitati, üks lükati tagasi, üks muudeti | 5 kriteeriumi ja liitumisvormi mockup; lugu sai 4 kriteeriumi (3 AI, 1 käsitsi muudetud) ja mockup'i | 37 s |
| 5. Kliendi täpsustus, eelvaade, rakendamine | „vaates peab olema näha klubi telefoninumber“: eelvaates uus kriteerium ja mockup'i muudatus; pärast rakendamist 5 kriteeriumi ja mockup v2; teised lood jäid samaks | 42 s |
| 6. AI ülevaatus leiab probleemi, liiga suur lugu jagatakse | 10 leidu, sh meelega lisatud liiga suur lugu; jagamise rakendamise järel oli backlog'is 8 lugu | 135 s |
| 7. Täpsustamist vajavat lugu ei saa märkida valmis arenduseks | keelduti, põhjusena näidati muu hulgas lahtist avatud küsimust | AI-d ei kasutata |
| 8. Serveri taaskäivitus ja projekti uus avamine | 8 lugu, mockup ja 18 sõnumit olid alles; AI pakkus jätkamiseks „Järgmine lugu“ ja „Lõpetame kohtumise“ | AI-d ei kasutata |
| 9. Sammud 1–5 ilma lugu või kriteeriumi nullist kirjutamata | täidetud | AI-d ei kasutata |

### Mudeli valik

Sama vastuvõtukatse korrati kolme mudeliga, et valida vaikimisi mudel (#25). Kõik kolm läbisid kõik sammud; erinesid kiirus ja mõnevõrra väljund.

| Samm | `gpt-6-astra`, madal | `gpt-6-luna`, keskmine | `gpt-6.1-sol`, madal |
| --- | --- | --- | --- |
| Esimene küsimus | 13 s | 6 s | 24 s |
| Rollidest lugudeni | 23 s | 17 s | 36 s |
| Kriteeriumid ja mockup | 37 s | 36 s | 47 s |
| Kliendi täpsustus | 42 s | 25 s | 50 s |
| Backlog'i ülevaatus | 135 s | 30 s | 226 s |

Valituks sai **`gpt-6-luna` keskmise mõtlemistasemega**: see oli igas sammus kiireim ja ainsana jäi backlog'i ülevaatus kindlalt alla 180-sekundilise ajalõpu, mida `gpt-6.1-sol` oleks ületanud. Luna soovitas alustada happy path'i esimesest loost, kriteeriumid olid kontrollitavad, kuid üldisemad kui teistel („Lehel kuvatakse klubi nimi.“). Sol pakkus ainult nõutud miinimumi ehk kolm kriteeriumi ja kasutas ingliskeelseid lõpujutumärke. Iga mudeliga tehti üks katse, nii et ajad on suunda näitavad, mitte täpsed. Mudel ja mõtlemistase on `.env` failis muudetavad (`AI_MODEL`, `AI_REASONING`).

## Mis jäi pooleli

- **Serverisse paigaldus (#21)** on ootel. Rakendus töötab praegu autori arvutis; paigalduse plaan (systemd teenus, Caddy, Codexi sisselogimine teenuse kasutajale, tracker samas masinas) on issue'sse kirja pandud.
- **Sisselogimine puudub.** Rakendus on ühe kasutaja tööriist. Avalikule aadressile paigaldades on vaja vähemalt parooli ette panna (vt README, „Turvalisus“).
- **Kaks lisavõimalust jäi tegemata:** kliendile jagatav vaatamislink backlog'ile ja mockup'idele ning kõnesisend kliendi täpsustuste jaoks.
- **Näidisrežiim** (`AI_PROVIDER=mock`) vastab ainult eesti keeles ja lihtsate etteantud vastustega. See on testide ja AI-ta demo jaoks, mitte päris kasutuseks.

## AI teadaolevad piirangud

Allpool on piirangud, mis tulid välja päris Codexiga katsetades. Mitu neist on serveri reeglitega leevendatud, kuid AI jääb ettepanekute tegijaks, mitte otsustajaks.

- **Aeglus.** Valitud mudeliga (`gpt-6-luna`, keskmine) võtab tavaline vestluse samm 6–17 sekundit, kliendi täpsustus umbes 25 sekundit, kriteeriumide ja mockup'i ettepanek umbes 35 sekundit ning uue vaate koostamine kirjelduse põhjal 30–75 sekundit. Backlog'i ülevaatus võttis seitsme looga 30 sekundit, kuid aeg sõltub mudelist ja backlog'i suurusest: teiste mudelitega kulus samale ülevaatusele 135 ja 226 sekundit. AI ajalõpp (`AI_TIMEOUT`, vaikimisi 180 sekundit) katkestab liiga pika päringu arusaadava veateatega; väga suure backlog'i korral tasub seda suurendada. Liides näitab ootamise ajal, et AI töötab ja kui kaua see võib kesta.
- **AI jätab vahel reegleid vahele.** Esimestes katsetes pakkus AI rollid kohe ilma täpsustava küsimuseta, kuulutas lugusid ilma neid kaartidena lisamata ja pakkus järgmise sammuna tegevust, mida nupp teha ei saa (näiteks „täpsusta lugu US-4“, mis tegelikult oleks jätkanud eelmise looga). Server kontrollib nüüd neid reegleid ja saadab rikkumise korral mudelile tagasiside ühe korduskatsega. Kui mudel ka teisel korral reeglit ei järgi, võetakse vastus vastu (välja arvatud kindlad piirid, näiteks kuni 3 täpsustavat küsimust ja ainult valitud loo muutmine, mida server alati jõustab).
- **Prioriteedi soovitus lähtub väärtusest, mitte järjekorrast.** AI soovitab alustada loost, ilma milleta ülejäänud töövoog on mõttetu (ülesande näite eeskujul), mitte tingimata happy path'i esimesest loost. Näiteks soovitas see alustada liitumissoovi saatmisest, sest see on samm, mis annab klubile kontakti. Põhjendus on alati kaardil näha ja kasutaja võib valida teise loo.
- **Kriteeriumide kvaliteet.** Kriteeriumid on enamasti kontrollitavad ja viitavad mockup'i elemendile, kuid kipuvad olema sarnase ülesehitusega („Lehel on …“, „Vormis on …“) ning jätavad vigade ja erijuhtude kriteeriumid pigem kõrvale, sest AI-l palutakse keskenduda põhitöövoole. Mittekontrollitavat kriteeriumi näeb kasutaja hoiatusena.
- **Kontrollitavuse reegel on lihtne.** See on sõnaloenditel põhinev reegel. See võib hoiatada ka siis, kui „ja“ on nimes või loetelus, mis tegelikult on üks tingimus (näiteks nupu nimi „Ostukorv ja maksmine“), ning ei tunne ära hinnangulisi sõnu, mida loendis pole. Hoiatus on vihje, otsustab kasutaja.
- **Mockup muutub AI käes tervikuna.** Täpsustuse korral kirjutab AI kogu vaate uuesti. Juhis nõuab muutumata komponentide id-de säilitamist ja eelvaade näitab muutunud osad, kuid AI võib vahel ka muutmata osi ümber sõnastada.
- **AI ei näe käsitsi joonistatud märkmeid.** Märkmed on inimese jaoks; AI arvestab ainult komponentide puud.
- **Liitsõnade ja käänete eripära.** Eestikeelse Connextra pealkirja jaoks peab AI andma rolli olevas käändes („Külastajana“). Käsitsi uut rolli lisades peab kasutaja selle vormi ise kirjutama; redaktor pakub seda, kui samas rollis lugu on juba olemas.
- **Isiklik tellimus.** Codex töötab autori ChatGPT tellimusega. See sobib ühe inimese tööriistaks, kuid mitme kasutajaga avaliku teenuse jaoks oleks vaja API võtit ja kasutuspiiranguid.
