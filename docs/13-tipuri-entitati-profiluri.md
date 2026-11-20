# Tipuri de entități și profiluri de funcționalitate

Aplicația nu mai e doar pentru ONG. Ca în 1C (unde la crearea bazei alegi configurația și apoi bifezi „Funcționalitatea”), la crearea unei baze noi utilizatorul răspunde la câteva întrebări, iar aplicația pornește **doar cu secțiunile, documentele, rapoartele și formulele potrivite** acelei firme.

> Principiu: **un singur nucleu comun** (cataloage, documente, înregistrări, bancă, casă, salarii, rapoarte, AI) + **profiluri** care pornesc sau opresc module. Nu se fac programe separate pentru fiecare tip de firmă.

## 1. Firmele contabilului-șef (cazurile reale de pornire)

| Firmă | Tip | Particularități |
|-------|-----|-----------------|
| Asociație / fundație | ONG | granturi, linii de buget, donatori, 616/716, ONG17, 5-CON |
| SRL — vânzare bunuri de uz casnic | SRL | stocuri, comerț cu amănuntul / ridicata, casă de marcat |
| SRL — magazin alimentar + fast-food | SRL | stocuri, **rețete / fișe de calculație** pentru fast-food, casă de marcat |
| SRL plătitor de TVA — magazin alimentar | SRL + TVA | **TVA**: facturi fiscale, e-Factura, registrele de cumpărări/vânzări, declarația TVA |
| SRL — bază de odihnă | SRL | servicii de cazare și alimentație, taxe locale (cazare) |
| Întreprindere individuală — magazin alimentar | ÎI | **partidă simplă**: registru-jurnal de venituri și cheltuieli, stocuri, casă de marcat |
| Gospodărie țărănească — mere de altoi (pomicultură) | GȚ | producție agricolă, recoltă, membrii GȚ, impozit specific GȚ, UNIF25 |

## 2. Expertul „Bază nouă” (pagina de start)

```
┌───────────────── Bazele mele ─────────────────┐
│  ● AO „CARTERA”                ONG            │
│  ● „Casa Bună” SRL             SRL, TVA        │
│  ● ÎI „Popescu Ion”            ÎI              │
│  ● GȚ „Livada Verde”           GȚ              │
│                                               │
│  [ + Bază nouă ]   [ Importă din 1C ]          │
└───────────────────────────────────────────────┘
```

Pașii expertului:

1. **Date de identificare**: IDNO (aplicația completează denumirea, adresa, CAEM din registrul public, dacă e disponibil), denumire, adresă.
2. **Forma juridică**: SRL / SA / ÎI / GȚ / ONG (asociație, fundație, instituție privată) / altele.
3. **TVA**: plătitor de TVA? de la ce dată?
4. **Regimul fiscal** (propus automat după răspunsuri, se poate schimba): regim general; impozit pe venitul din activitatea operațională (IVAO) pentru IMM; regimul GȚ; regimul ONG.
5. **Genuri de activitate** (se pot bifa mai multe): comerț cu amănuntul, comerț cu ridicata, alimentație publică / fast-food, producție, prestări servicii, cazare / turism, agricultură, granturi / activitate necomercială.
6. **Angajați**: are salariați? (pornește salarizarea, IPC21)
7. **Sursa datelor**: bază goală / **import din 1C** / import din fișiere Excel.
8. **Rezumat**: „Vor fi pornite: Stocuri, Casă de marcat, TVA, Rețete…”, apoi **Creează**.

După creare, orice opțiune se poate schimba din **Administrare → Funcționalitate** (exact ca în 1C), cu data de la care se aplică.

## 3. Ce pornește fiecare răspuns

| Răspuns | Module / secțiuni pornite | Rapoarte în calendar |
|---------|---------------------------|----------------------|
| SRL / SA | partidă dublă, plan de conturi general, situații financiare | situațiile financiare anuale, declarația impozitului pe venit |
| **ÎI** | **partidă simplă**: registru-jurnal de venituri și cheltuieli, registrul mijloacelor fixe, inventar; fără plan de conturi | declarația pe venit a ÎI |
| **GȚ** | partidă simplă (sau dublă, la alegere), **membrii GȚ**, recoltă / producție agricolă, distribuirea venitului către membri | UNIF25 (secțiunea GȚ) / VEN12 |
| ONG | granturi, bugete, donatori, conturile 616/716, fonduri 341 | ONG17, 5-CON, rapoarte donatori |
| **Plătitor TVA** | facturi fiscale, e-Factura obligatorie, registrele de cumpărări/vânzări, TVA la import servicii | declarația TVA lunară |
| Comerț cu amănuntul | **stocuri**, **case de marcat**, rapoarte Z, adaosuri comerciale | — |
| Comerț cu ridicata | stocuri, liste de prețuri, facturi | — |
| **Alimentație publică / fast-food** | **rețete și fișe de calculație**, consum de materie primă la vânzare, pierderi tehnologice | — |
| Producție | rețete / specificații, documente de producție, cost de producție | — |
| Cazare / turism | servicii de cazare, unități de cazare | taxa locală pentru unitățile de cazare (TL) |
| Agricultură | culturi / livezi, recoltă, consum de materiale pe culturi | — |
| Salariați | salarizare, CIM/civil, scutiri | IPC21 |
| Mijloace fixe | fișe MF, amortizare (în închiderea lunii) | — |

Tabelul e păstrat ca **date** (`features` → module, secțiuni, documente, rapoarte, șabloane de formule), deci se poate completa fără cod nou.

## 4. Partida simplă (ÎI, GȚ) vs partida dublă

- Aceleași documente (facturi, plăți, încasări, casă, salarii), dar **motorul de înregistrare** diferă:
  - partidă dublă → `entry_lines` (Dt/Kt);
  - partidă simplă → `simple_ledger_entries`: venit = încasare, cheltuială = plată, cu categoria (deductibilă / nedeductibilă).
- Registru-jurnal de venituri și cheltuieli, registrul MF, lista de inventar și declarațiile se generează din `simple_ledger_entries`.
- Dacă o ÎI/GȚ trece la partidă dublă (ex. devine plătitor de TVA), aplicația propune soldurile de deschidere.

## 5. Regimurile fiscale ca date

Cotele și condițiile se schimbă des (ex. cota GȚ: 7% în 2026, majorare propusă la 12% din 2027; condițiile IVAO 4% revizuite în politica fiscală 2027). Deci:
- regimul organizației se ține în `organization_tax_regimes` cu perioadă (`valid_from` / `valid_to`);
- cotele în `tax_rates` (deja existent), aprobate de contabilul-șef;
- monitorul legislativ (asistentul AI) semnalează propunerile și legile adoptate.

## 6. Ordinea de implementare (pentru teză și pentru produs)

| Etapă | Profil | De ce |
|-------|--------|-------|
| 1 | **Nucleul comun + ONG** | cazul cel mai complex, deja analizat (1C ONG) |
| 2 | **SRL** (partidă dublă, stocuri, casă de marcat, TVA) | configurația SRL din 1C, cea mai răspândită |
| 3 | Alimentație publică (rețete), cazare | se construiesc peste stocuri |
| 4 | **ÎI** (partidă simplă) | alt motor de înregistrare, documente comune |
| 5 | **GȚ** (agricultură, membri) | peste partida simplă |

Pentru examen / teză e suficientă etapa 1 + o parte din etapa 2 (arată că arhitectura cu profiluri funcționează); restul — dezvoltarea produsului după susținere.

## Surse

- [Monitorul Fiscal — evidența contabilă a persoanelor fizice care desfășoară activități independente](https://monitorul.fisc.md/en/editorial/reglementarea-evidentei-contabile-inute-de-catre-persoanele-fizice-care-desfasoara-activitati-independente.html)
- [ASEM — partida simplă la întreprinderile individuale (conferință 2025)](https://irek.ase.md/jspui/bitstream/123456789/4297/1/ASEM_INTERNATIONAL_CONF_ISSC_14-15%20martie%202025_p125-127.pdf)
- [Monitorul Fiscal — gospodăriile țărănești (de fermier), regimul fiscal](https://monitorul.fisc.md/ru/gospodariile-taranesti-de-fermier-regimul-fiscal/)
- [Monitorul Fiscal — Politica fiscală 2027: va crește cota impozitului pentru unii contribuabili](https://monitorul.fisc.md/politica-fiscala-2027-va-creste-cota-impozitului-pentru-unii-contribuabili/)
- [SFS — formularul UNIF25](https://sfs.md/uploads/blank/215/document/forma-unif25pdf-685251c886f840.20509215.pdf)
- [Monitorul Fiscal — aplicarea impozitului pe venit din activitatea operațională (IMM)](https://monitorul.fisc.md/ru/tax_practice/aspecte-ale-aplicarii-impozitului-pe-venit-din-activitatea-operationala-a-agentilor-economici--subiecti-ai-sectorului-imm.html)
- [Monitorul Fiscal — Politica fiscală 2027, modificări privind impozitul pe venit](https://monitorul.fisc.md/politica-fiscala-2027-modificari-privind-impozitul-pe-venit/)
- [KPMG — Tax Card Moldova 2026](https://assets.kpmg.com/content/dam/kpmg/md/pdf/2026/Tax-Card-MD-2026-RO.pdf)

> Detaliile pentru ÎI și GȚ (formularele exacte, plafoanele, cotele) se verifică la implementarea etapelor 4–5 în Codul fiscal în vigoare și în configurația 1C pentru aceste forme, dacă va fi disponibilă.
