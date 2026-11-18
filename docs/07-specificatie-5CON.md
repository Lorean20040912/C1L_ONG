# Specificația raportului statistic 5-CON

**Formular:** 5-CON — *Consumurile și cheltuielile organizațiilor necomerciale*
**Destinatar:** Biroul Național de Statistică
**Periodicitate:** trimestrial (termen — ziua 25 a lunii următoare trimestrului, conform calendarului din 1C)
**Unitate:** **mii lei, cu zecimale**
**Sursa analizei:** raportul `НКО_Статистический5CON` din 1C — macheta tabelului și schema XML `5CON_xsd_2023`

## 1. Antet (`Header`)

| Element XML | Conținut | Sursa |
|-------------|----------|-------|
| `ENT_NAME` | denumirea | `organizations.name` |
| `IDNO` / `FISC` | cod fiscal | `organizations.idno` |
| `CUIIO` | cod statistic CUIIO | `organizations.cuiio` |
| `CFOJ`, `CFP` | forma organizatorico-juridică, forma de proprietate | `organizations.cfoj`, `cfp` |
| `CAEM`, `CUATM` | activitate, localitate | `organizations.caem`, `cuatm` |
| `STREET`, `STREET_NR`, `PHONE`, `EMAIL` | adresă, contacte | organizație |
| `YEAR`, `TRIM`, `DATE_FISC` | anul, trimestrul | perioada raportului |
| `HEAD`, `EXECUTOR` | conducător, executor | organizație / utilizator |
| `flag1` / `flag2` | A. A avut activitate în trimestru? Da / Nu | automat: există înregistrări în trimestru |

## 2. Capitolul 1 — rânduri (`CAP1_R{rând}_C1`, coloana 1 = realizat în trimestru)

### Venituri

| Rând | Indicator | Calcul |
|-----:|-----------|--------|
| **010** | Venituri – total | 011 + 012 + 018 + 024 + 030 |
| 011 | Contribuțiile fondatorilor și membrilor | |
| **012** | Mijloace cu destinație specială | 014 + 015 + 016 + 017 |
| 013 | – din care: din străinătate | granturi cu donator nerezident |
| 014–017 | inclusiv: active imobilizate / stocuri / servicii / numerar (mijloace financiare) | după forma în care s-a primit |
| **018** | Mijloace nepredestinate | 020 + 021 + 022 + 023 |
| 019 | – din care: din străinătate | |
| 020–023 | inclusiv: active imobilizate / stocuri / servicii / numerar | |
| **024** | Venituri din activitatea economică | 025 + … + 029 |
| 025–029 | produse finite / mărfuri / servicii / arendă curentă / alte | |
| 030 | Alte venituri (alte intrări) | |

### Consumuri și cheltuieli

| Rând | Indicator | Calcul |
|-----:|-----------|--------|
| **040** | Consumuri și cheltuieli – total | 050 + 070 + 090 + 100 + 110 + 120 |
| **050** | Materiale – total | 051 + 052 + 053 + 054 + 055 + 060 + 061 + 062 + 063 + 069 |
| 051–054 | materii prime și materiale / piese de schimb / materiale de construcție pentru reparație / ambalaje | |
| 055 | combustibil – total (056 produse petroliere + 057 cărbune + 058 gaze + 059 alte) | |
| 060–063, 069 | energie electrică / termică / apă / OMVSD / alte materiale | |
| **070** | Servicii prestate de terți – total | 071 + 072 + 073 + 075 + … + 082 + 089 |
| 071–073 | transport / comunicații / reparația mijloacelor fixe (074 – din care curentă) | |
| 075–082, 089 | prelucrare / bancare / audit / notariale-juridice / pompieri-pază / publicitate / instruire / canalizare-gunoi-lift / alte servicii | |
| **090** | Uzura (amortizarea) – total (091 mijloace fixe + 092 active nemateriale) | |
| **100** | Retribuirea muncii | |
| **110** | Contribuții CNAS + CNAM (111 + 112) | |
| **120** | Alte cheltuieli operaționale – total | 130 + 140 + 150 + … + 230 |
| 130 (131) | arendă operațională (din care terenuri) | |
| 140 (141, 142) | deplasări (din care cazare, diurnă) | |
| 150, 160 | protocol / asigurare obligatorie | |
| 170 (171–174) | dobânzi (nerezidenți / rezidenți; instituții financiare / întreprinderi) | |
| 180, 190, 200, 210 | datorii dubioase / amenzi / valoarea activelor curente ieșite / **donații și sponsorizări** | |
| 220 (221–225) | impozite și taxe în cheltuieli (funciar / imobiliar / rutier / locale / alte) | |
| 230 | alte cheltuieli | |

### Informativ

| Rând | Indicator | Sursa |
|-----:|-----------|-------|
| 300 | Numărul membrilor la ultima zi a trimestrului | `organizations.members_count` (pe perioadă) |
| 310 | Numărul mediu al salariaților | calculat din contracte CIM active |
| 320 | Numărul de voluntari | `organizations.volunteers_count` (pe perioadă) |

## 3. Cum se completează automat

Ca în 1C: fiecare **articol de cheltuieli** (`cost_items`) are rândul lui din 5-CON (`con5_article`, ex. `071`). Liniile de buget sunt legate de articole, iar înregistrările contabile au articolul → raportul se obține prin însumare pe `con5_article` pentru trimestru, împărțit la 1000.

Veniturile (rândurile 011–030) se obțin din conturile de venituri + tipul activității (`special_purpose` / `other` / `economic`) + forma primirii (active / stocuri / servicii / numerar) + țara donatorului.

## 4. Reguli de verificare

1. Toate rândurile „total” = suma componentelor (formulele de mai sus).
2. `013 ≤ 012`, `019 ≤ 018`, `074 ≤ 073`, `131 ≤ 130`, `141 + 142 ≤ 140`.
3. `100` și `110` = datele din salarizare pentru trimestru (verificare încrucișată cu IPC21).
4. Dacă `flag` = „Nu”, toate rândurile = 0.
