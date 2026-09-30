# Demo (5–10 minutit)

Demo näitab ülesande nõutud käiku: projekt luuakse, juhitud vestlus koostab esialgse backlog'i, üks lugu prototüübitakse koos kliendi täpsustusega ja backlog groomitakse. AI vastab tavaliselt 10–20 sekundiga; kriteeriumide ja mockup'i ning ülevaatuse koostamine võtab kuni minuti, seega tasub nende ootamise ajal rääkida, mida parasjagu näha on.

## Ettevalmistus

- `.env` failis on `AI_PROVIDER=codex` ja Codex on sisse logitud (`codex login --device-auth`).
- Server käib (`./start.sh`) ja brauseris on avatud projektide leht.
- Soovi korral on Agile Tracker käimas ja `.env` failis on `TRACKER_URL`, et lõpus saatmist näidata.

## Käik

1. **Projekt ja idee (1 min).** Uue projekti vormis vali mall „Spordiklubi veeb“ või kirjuta ise üks ähmane lause, näiteks „Spordiklubi tahab veebi, kus saab treeningutega tutvuda ja liikmeks astuda.“ Loo projekt ja saada idee.
2. **Täpsustavad küsimused ja rollid (1–2 min).** AI küsib täpsustava küsimuse koos vastusevariantidega. Näita, et saab klõpsata, valida „Muu (kirjutan ise)“ või küsimuse vahele jätta. Kinnita pakutud rollid, eemaldades ühe linnukese.
3. **Lood happy path'i järjekorras (1 min).** AI pakub 5–8 lugu põhitöövoo järjekorras. Võta üks linnuke ära ja vajuta „Lisa valitud“. Lood ilmuvad paremale backlog'i.
4. **Millest alustada (30 s).** AI soovitab loo koos põhjendusega. Näita, et backlog'i järjekorda saab lohistades või noolenuppudega muuta, ja vajuta „Nõus, alustame sellest“.
5. **Kriteeriumid ja mockup (2 min).** Oota ettepanekut. Osuta hiirega kriteeriumile, et näha mockup'is vastavat elementi. Kinnita üks, eemalda üks ja muuda üht käsitsi, seejärel „Kinnita kõik“.
6. **Kliendi täpsustus (1–2 min).** Kirjuta näiteks „Klient ütleb, et hinna juures peab olema näha, kas see sisaldab käibemaksu.“ Näita eelvaadet (enne ja pärast) ning rakenda. Ava lugu backlog'is ja mockup'i versiooniajalugu, et näha muudatust mõlemas.
7. **Uus vaade kirjeldusest (1 min).** Vajuta backlog'i juures „+ Uus vaade“ ja kirjuta näiteks „Leht, kus tutvustatakse klubi treenereid: pilt, spordiala ja tunniplaan.“ AI pakub loo, kriteeriumid ja mockup'i korraga; vajadusel pakub ta ka uue rolli. Vaata üle ja vajuta „Lisa backlog'i“.
8. **Groomimine (2 min).** Lisa käsitsi liiga suur lugu (näiteks „registreeruda, tasuda liikmetasu ja broneerida treening“) ja vajuta „Vaata backlog üle“. Rakenda jagamise ettepanek ja näita, kuidas kriteeriumid jaotusid. Märgi üks lugu täpsustamist vajavaks koos avatud küsimusega ja näita, et seda ei saa „Valmis arenduseks“ staatusesse panna.
9. **Püsivus (30 s).** Taaskäivita server (`./start.sh`) ja laadi leht uuesti: backlog, mockup'id ja vestlus on alles ning AI pakub jätkamiseks sobivat sammu.
10. **Lisaks, kui aega jääb.** Saada lood Agile Trackerisse, joonista mockup'ile märge või vaheta liidese keelt päisest.
