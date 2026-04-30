# Brugsvejledning

Denne vejledning er til dig, der skal bruge chatten til at slå dansk
skatte- og regnskabsret op. Den er ikke skrevet til udviklere eller
operatører.

For overblik over hvad systemet kan og ikke kan, se [`PRODUCT.md`](../PRODUCT.md).

---

## 1. Hvad kan du spørge om?

Chatten er bygget på et korpus af dansk skatte- og regnskabsret
(Afskrivningsloven, Årsregnskabsloven, Bogføringsloven, Momsloven,
Selskabsskatteloven, Ligningsloven m.fl. — i alt 9 love og 3
bekendtgørelser). Du får de bedste svar når dit spørgsmål handler om
disse områder.

### Eksempler på gode spørgsmål

- "Kan jeg fradrage indkøb af en computer som driftsudgift?"
- "Hvilke krav er der til bogføringsbilag?"
- "Hvad er reglerne for moms ved EU-handel?"
- "Hvordan afskrives goodwill skattemæssigt?"
- "Hvornår skal et selskab aflægge årsrapport efter regnskabsklasse C?"
- "Hvad er fristen for at klage over en skatteansættelse?"

Spørgsmål som disse rammer direkte ned i lovteksten, og du får et svar
med præcise paragrafhenvisninger.

### Eksempler på spørgsmål der ikke passer godt

- **Konkret juridisk rådgivning:** "Kan jeg sagsøge SKAT for…" — chatten
  forklarer regler, men giver ikke rådgivning i din konkrete sag. Tal
  med en advokat eller skatterådgiver.
- **Andre jurisdiktioner:** "Hvordan beskattes udbytte i Tyskland?" —
  korpusset dækker kun dansk ret.
- **Aktiehandel og kursgevinster:** "Kan jeg fratrække tab på aktier i
  et ApS?" — Aktieavancebeskatningsloven (ABL) er ikke i korpusset
  endnu, så svaret bliver svagt. ABL er på roadmappet.

Hvis du får et svar der virker tyndt eller forkert, så tjek først om
emnet ligger uden for korpusset.

---

## 2. Chatten

### Sådan stiller du et spørgsmål

Skriv dit spørgsmål i feltet nederst på siden og tryk **Send** — eller
tryk Enter. Shift+Enter laver linjeskift hvis du vil dele spørgsmålet
op over flere linjer.

### Hvordan svaret kommer frem

Svaret skrives ord for ord mens modellen genererer det (streaming).
Det er normalt. Når svaret er færdigt, dukker en panel med
referencer op nedenunder.

### Hvis svaret går i stå

Der er ikke nogen "prøv igen"-knap i v1.x. Hvis et svar går i stå
eller fejler:

1. Genindlæs siden (F5 / Cmd+R).
2. Stil spørgsmålet på ny — eventuelt omformuleret.

Hvis det sker gentagne gange er det værd at melde til operatøren.

### Admin-linket

Nederst i sidepanelet er der et lille "Admin"-link. Det fører til en
side for operatøren der vedligeholder korpusset — det er ikke
relevant for almindelig brug. Se afsnit 6.

---

## 3. Læsning af svar

Svaret citerer paragrafferne det bygger på. Det ser typisk sådan ud
inde i teksten:

> Udgifter til driftsmidler kan fradrages efter afskrivningsreglerne
> (AFL § 5, stk. 1). Bogføringspligtige skal opbevare regnskabsmateriale
> i 5 år (BOG § 12).

### Sådan læser du citaterne

- **AFL, MOML, BOG osv.** er lovkoder — se tabellen i afsnit 4.
- **§** er paragraf­tegnet (lovens hovednummer).
- **stk.** står for *stykke* — det er en underinddeling af paragraffen.
  "stk. 1" er det første afsnit, "stk. 2" det næste, og så videre.
- **nr.** står for *nummer* — det er en endnu finere opdeling, typisk
  en punktopstilling inde i et stykke.

Eksempel: "AFL § 5, stk. 1, nr. 2" betyder Afskrivningsloven, paragraf
5, stykke 1, punkt 2.

### Reference­panelet under svaret

Under svaret ligger en liste over hver enkelt citeret paragraf med
fuld lovtekst. Hver reference viser:

- Citatlabel (fx "AFL § 5, stk. 1") som klikbart link
- Lovens fulde navn
- Et uddrag af paragrafteksten — tryk "Læs mere" for at se hele teksten
- En relevansscore i højre side (jo højere, jo bedre matcher)

Klik på citatlabelet for at åbne paragraffen direkte på
[retsinformation.dk](https://www.retsinformation.dk) — det er den
officielle kilde, og det er der du finder den fulde, opdaterede lovtekst.

---

## 4. Filtreret søgning (lov-filteret)

Over chatten ligger en dropdown ("Filtrer lov:"). Den begrænser
søgningen til én bestemt lov.

- **Brug filteret** når du ved hvilken lov der er relevant — fx hvis
  du udelukkende vil have svar fra Momsloven.
- **Lad det stå på "Alle love"** når du er i tvivl, eller når
  spørgsmålet krydser flere love. Det er det normale udgangspunkt.

Når du vælger "Alle love" søger systemet på tværs af hele korpusset og
finder selv frem til de relevante paragraffer.

### De 12 lovkoder

| Kode      | Populært navn                          |
|-----------|----------------------------------------|
| AFL       | Afskrivningsloven                      |
| ARL       | Årsregnskabsloven                      |
| BOG       | Bogføringsloven                        |
| SEL       | Selskabsskatteloven                    |
| MOML      | Momsloven                              |
| LL        | Ligningsloven                          |
| SKL       | Skattekontrolloven                     |
| REVL      | Revisorloven                           |
| SFL       | Skatteforvaltningsloven                |
| BOG-BEK   | Bogføringsbekendtgørelsen              |
| BOG-MBK   | Mindstekravsbekendtgørelsen for bilag  |
| MOML-BEK  | Momsbekendtgørelsen                    |

---

## 5. Sessioner og historik

Hver samtale gemmes som en session i venstre sidepanel.

- **Sessioner ligger i din browser** (localStorage). De følger ikke
  med hvis du skifter til en anden enhed eller en anden browser.
- **Ingenting ligger på en server bundet til dig som bruger.** Der er
  ingen login i v1.x.
- **"Ny samtale"** (knappen nederst i sidepanelet) starter en frisk
  session uden at slette de gamle.
- **Slet en samtale** ved at holde musen over den i listen og trykke
  på papirkurv-ikonet.
- **Rydder du dine browserdata** (cookies, lokal lagring) forsvinder
  hele historikken. Der er ingen backup.

Hvis du har brug for at gemme et svar, så kopiér det ud af chatten —
fx ind i et notat eller en e-mail.

---

## 6. Administrationssiden (/admin)

`/admin`-siden er beregnet til den operatør der vedligeholder
korpusset. Den viser hvilken version af hver lov der er indlæst,
hvornår der senest blev tjekket for opdateringer mod
retsinformation.dk, og en knap der manuelt kan trigge et nyt tjek.

Som almindelig bruger kan du ignorere siden. Den ændrer ikke noget
for hvordan du stiller spørgsmål eller læser svar.

---

## 7. Begrænsninger og kendte problemer

- **Det er et værktøj, ikke juridisk rådgivning.** Brug svarene som
  udgangspunkt for din egen vurdering, ikke som facit i en konkret
  sag.
- **Kun dansk skatte- og regnskabsret.** Andre retsområder
  (familieret, strafferet, udlændingeret osv.) er ikke i korpusset.
- **Aktieavancebeskatningsloven (ABL) mangler.** Spørgsmål om
  aktietab og kursgevinster giver derfor svage svar. ABL er på
  roadmappet.
- **BOG-MBK** (Mindstekravsbekendtgørelsen) returnerer i øjeblikket
  kun to paragraffer efter live-hentning fra retsinformation-api.dk
  — årsagen undersøges.

For den fulde liste over begrænsninger, version­historik og hvad der
ligger i pipelinen, se [`PRODUCT.md`](../PRODUCT.md) under "Current
limitations".

Den autoritative kilde til dansk lovgivning er altid
[retsinformation.dk](https://www.retsinformation.dk). Hvis et svar i
chatten og den officielle lovtekst er uenige, har lovteksten ret.
