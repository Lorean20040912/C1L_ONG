# Schimbul cu băncile

Sursa: fișierele-exemplu descărcate din sistemele băncilor (păstrate local, **nu** în GitHub) și documentația publică a băncilor. Aici e descrisă doar **structura** formatelor, fără date.

## 1. Import extrase — formatele găsite

| Bancă | Fișier | Format | Observații |
|-------|--------|--------|------------|
| **MAIB** | `*_EN_TXT.txt` | text, separator `^`, primul rând — antet cu nume de câmpuri, al doilea — soldul | câmpuri: `DATA NDOC DC ST CCL CCOR CFC CFCCOR CBC DENC DENCT TV SUMN SUML TD DE1 DE2 DE3 DE4 PRI DAT_TR DAT_AC BIC COD_TRANZ URGENT` |
| MAIB | `*.csv` | aceleași câmpuri, separator `,`, data `dd-mm-yyyy` | |
| MAIB | `*.dbf` | DBF cu aceleași câmpuri (`DATA:D8`, `SUMN:N15`, `DE1..DE4` = destinația) | |
| MAIB | `h*.dbf` + `i*.dbf` („DBF UA”) | antet (`BEGIN_DATE, ACCOUNT, OPEN_BAL, C_TURNOVER, D_TURNOVER, CLOSE_BAL`) + rânduri (`OPER_TYPE, DOC_DATE, DOC_NUMBER, AMOUNT, P_ACCOUNT, PAYER, P_FCODE, R_ACCOUNT, RECEIVER, R_FCODE, GROUND…`) | |
| MAIB | `*_DBO.txt` | **1CClientBankExchange** (`SECTIONACCOUNTSTART … DocStart … DocEnd`) | |
| **Moldindconbank** | `*.txt` | **1CClientBankExchange(V:M.1)** | aceleași chei ca MAIB DBO + `CREDITSUBACCOUNTNAME` |
| Moldindconbank | `*.csv` | același format, pe un rând per document (`DocStart,CHEIE=valoare,…`) | |
| Moldindconbank | `*.xml`, `*.xls` | XML `ROWDATA/ROW` | |
| **FinComBank** | `*.txt` | rânduri cu **lățime fixă** (~460 caractere): BIC, IBAN, cod fiscal, sumă, valută, destinație | documentația FinComBank pentru poziții — de la contabil |
| FinComBank | `*.xml`, `*.xls` | XML `ROWDATA/ROW` | |
| **OTP Bank** | TXT / DBF 1C / DBF / DBF UA | după manualul OTP Internet Banking PJ (cap. 11) — TXT e în stil 1CClientBankExchange | lipsește fișier-exemplu |
| **Victoriabank** | — | de obținut fișier-exemplu și documentația | |

**Concluzie:** 3 „familii” de formate acoperă aproape tot:
1. **1CClientBankExchange** (cheie=valoare) — MAIB DBO, Moldindconbank, OTP TXT;
2. **tabel cu câmpuri MAIB** (`DATA NDOC DC … SUMN … DE1–DE4`) — în TXT `^`, CSV, DBF — MAIB, OTP DBF 1C;
3. **lățime fixă / XML ROWDATA** — FinComBank, Moldindconbank XML.

Deci parserele sunt: `ClientBankExchangeParser`, `DelimitedParser` (separator configurabil), `DbfParser`, `FixedWidthParser`, `RowDataXmlParser`. Profilul băncii (`bank_formats.layout`) spune doar ce parser și ce coloană înseamnă ce.

Câmpuri normalizate la import: data, nr. document, debit/credit, IBAN-ul nostru, IBAN contrapartidă, cod fiscal contrapartidă, denumire, sumă, valută, destinație, cod tranzacție. Cheia anti-dublură: `IBAN + dată + nr. document + sumă + D/C`.

## 2. Export ordine de plată (din aplicație în bancă)

### Structura de import cunoscută — OTP Bank (plată în MDL)

| # | Câmp | Lungime | Conținut | Statut |
|---|------|--------:|----------|--------|
| 1 | `DATAV` | 8 | data valutării `AAAALLZZ` | obligatoriu |
| 2 | `NDOC` | 10 | nr. document | obligatoriu |
| 3 | `CCL` | 24 | IBAN plătitor | obligatoriu |
| 4 | `CFC` | 13 | cod fiscal plătitor | obligatoriu (rezidenți) |
| 5 | `CSC` | 4 | cod subdiviziune | câmp obligatoriu, valoare opțională |
| 6 | `CCOR` | 24 | IBAN beneficiar | obligatoriu |
| 7 | `DENC` | 105 | denumirea beneficiarului | obligatoriu |
| 8 | `REZB` | 1 | rezident R / nerezident N | obligatoriu |
| 9 | `CFCCOR` | 13 | cod fiscal beneficiar | obligatoriu (rezidenți) |
| 10 | `SUMN` | 15 | suma (cu punct; în DBF `N` cu 2 zecimale) | obligatoriu |
| 11 | `TC` | 3 | valuta (`MDL`) | obligatoriu |
| 12 | `DE` | **210** | destinația plății | obligatoriu |
| 13 | `URGENT` | 1 | `U` urgent / `N` normal | obligatoriu |

### Formatele de export găsite în configurația 1C (prelucrarea de schimb cu banca)

Configurația 1C ONG are câte o funcție de export pentru fiecare bancă. Le folosim ca **referință verificată în practică** (aceste fișiere sunt acceptate de bănci astăzi):

| Bancă (setarea „Programa” din 1C) | Format | Structura |
|---|---|---|
| **MAIB** („DBF MAIB”, „DBF MAIB 2024”, „TXT MAIB”) | DBF | câmpuri: `Data D`, `NDOC S10`, `CCL S30`, `CCOR S30`, `CCORT S30` (cont trezorerial), `CFC S18`, `CFCCOR S18`, `CBC N3`, `DENC S55` (prefix `(R) `), `DENCT S50`, `SUMN N15.2`, `TD N2` (=8), `DE1 S220`, `DE2 S220`, `DE3`, `DE4`, `BIC S220`, `URGENT S1` (U/N). **Primul rând = totalul lotului** în `SUMN`, apoi câte un rând pe ordin. Destinația: primele 250 de caractere în `DE1`, restul în `DE2`. Pentru conturi în valută — funcție separată |
| MAIB valută | DBF | variantă a celei de mai sus pentru plăți în valută |
| **FinComBank** („DBF FinCom”, „XML FinComBank”) | XML `ROWDATA/ROW` cu atribute | `BIC_A, ACCOUNTNO, BIC_B, CORRACCOUNTNO, CORRTREZACCOUNTNO, TRANSACTIONCODE` (101 = plată la buget, 001 = obișnuită), `DOCUMENTNO, DOCUMENTDATE (yyMMdd), AMOUNT, CORRFISCALCODE, CORRSNAME, DETAILSOFPAYMENT, CORRRESIDENCY (R/N), PRIORITY (U/N), SUBDIVISIONCODE, CORRSUBDIVISIONCODE, RESIDENCY, CONTRAGENTSNAME, FISCALCODE, TREZACCOUNTNO, VALUEDATE, STATENAME, ADDDETAILSOFPAYMENT, IBAN_A, IBAN_B` |
| **OTP Bank** („DBF OTP Bank”, „DBF OTP Bank 2019”) | DBF | structura OTP de mai sus (`DATAV … URGENT`) |
| **Victoriabank, Moldindconbank, Unibank, Energbank, Banca Socială, ProCredit** („Система BS-Client”) | TXT **1CClientBankExchange(V:M.1)** | antet `BEGINDATE, ENDDATE, SECTIONACCOUNTSTART, DATE, ACCOUNT, STARTREST, INCOME, OUTCOME, STOPREST, CURRCODE, SECTIONACCOUNTSTOP`, apoi pe fiecare ordin `DocStart … DocEnd` cu `DOCID, DOCUMENTNUMBER, DOCUMENTDATE, DATEWRITTEN, PAYERACCOUNT, PAYERFCODE, CODEDEP, PAYERBANKBIC, PAYER, PAYERBANK, RECEIVER, RECEIVERFCODE, RECEIVERACCOUNT, RECEIVERBANKBIC, RECEIVERBANK, RESIDENCE, AMOUNT, GROUND, OPERTYPE, TRANSACTIONCODE, TRANSFERTYPE, DEBETSUBACCOUNT, CREDITSUBACCOUNT`. Moldindconbank și Energbank au mici variații (parametru separat în 1C) |
| Comertbank | XML | funcție separată |
| EXIM, EuroCreditBank | TXT / DBF | funcții separate |

**Deci Victoriabank primește fișierul în formatul BS-Client (1CClientBankExchange)** — același format în care Moldindconbank dă extrasele. MAIB primește DBF.

Reguli comune observate în 1C, pe care le păstrăm:
- suma exportată = suma documentului fără TVA reținut la sursă (dacă e cazul);
- numărul documentului fără liniuțe și prefixe, doar cifre;
- din destinație se scot caracterele `%` și rândurile noi;
- ordinele exportate se marchează „exportat”;
- plățile către buget au cod de tranzacție special (`101`) și cont trezorerial.

### Pachetul de export „pe zi / pe oră”

Butonul **„Exportă în bancă”** din lista ordinelor de plată:
1. ia ordinele de plată **selectate** (sau toate cele pregătite pentru o zi / după o oră);
2. le grupează **pe bancă și pe cont plătitor**;
3. creează în sursa de documente (Drive / folder local) folderul
   `Bancă / Export / <Banca> / <AAAA-LL-ZZ_HHmm> /` cu fișierul (sau fișierele) în formatul băncii: `plati_<IBAN>.txt` / `.dbf`;
4. marchează ordinele ca *exportate* (cu legătura la lot); un ordin exportat nu se mai exportă din greșeală a doua oară (doar cu confirmare).

Contabilul încarcă fișierul în sistemul băncii. La importul extrasului următor, plățile se potrivesc automat cu ordinele exportate (după nr. document + sumă + IBAN).

## 2a. Formele de tipar

Configurația 1C are machetele formelor tipizate (ordin de plată, dispoziții de casă, factură fiscală, acte etc.), care sunt la zi. Le folosim ca **model de așezare** pentru formele noastre PDF, iar la implementare fiecare formă se compară cu formularul oficial în vigoare (Ministerul Finanțelor / SFS — formularele tipizate, documentele primare cu regim special). Formele au versiune și dată de valabilitate, ca rapoartele (`report_forms`).

## 3. Plata cumulată a impozitelor și contribuțiilor

**Practica actuală:** ca să nu plătească comision pentru fiecare angajat, contabilul face **un singur ordin de plată** pe tip de obligație (ex. toate contribuțiile CNAS ale unui proiect) și scrie în destinație, pe nume, suma fiecăruia.

**În aplicație — documentul „Plată cumulată a impozitelor din salariu”:**
1. se alege perioada (luna), proiectul/grantul (sau „toate”) și tipul: *impozit pe venit*, *CNAS (CAS)*, *CNAM (CAM)*;
2. aplicația ia sumele din calculul salariului (`payroll_entries`) și creează **un ordin de plată** cu suma totală și **rândurile pe persoane** (nume, sumă);
3. destinația se generează automat, ex.:
   `CAS 10.2026 proiect SOR-2026-01: Popescu I. 1 234,00; Rusu M. 980,50; …`
4. **limita câmpului destinație** depinde de bancă (OTP — 210 caractere; MAIB — 2 câmpuri `DE1` + `DE2`): dacă lista cu nume și prenume nu încape, aplicația lasă **doar numele de familie** și suma (`CAS 10.2026 SOR-2026-01: Popescu 1 234,00; Rusu 980,50; …`); dacă nici așa nu încape — propune împărțirea în 2 ordine;
5. contabilitatea primește înregistrări corecte pe fiecare persoană și pe fiecare grant (datoria fiecăruia se stinge), iar comisionul bancar e unul singur.

Tabele: `payment_orders` (antetul) + `payment_order_lines` (persoană, sumă, grant, rândul din calculul salariului) + `payment_batches` (lotul de export pe zi/oră).
