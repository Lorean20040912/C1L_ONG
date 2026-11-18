# Specificația declarației ONG17

**Formular:** ONG17 — *Declarația cu privire la impozitul pe venit pentru organizațiile necomerciale*
**Temei:** Ordinul MF nr. 08 din 15.01.2018, Anexele 1–2, **modificat prin Ordinul MF nr. 64 din 25.06.2025**
**Cine depune:** organizațiile necomerciale prevăzute la art. 52 din Codul fiscal
**Periodicitate:** anual
**Sursa:** formularul și instrucțiunea din folderul proiectului (`Forma ONG17.pdf`, `Instructiune (ro).pdf`)

> În configurația 1C actuală **nu există** — se completa manual. În aplicația noastră e funcție nouă.

## 1. Antet

| Câmp | Sursa |
|------|-------|
| Perioada fiscală | anul raportului |
| Categoria contribuabilului (bifă): A Asociație obștească, B Fundație, C Organizație filantropică, D Culte religioase, E Partide politice, F Publicații periodice / agenții de presă, G Alte ONG | `organizations.ngo_category` |
| Denumirea contribuabilului (ca în actele de constituire) | `organizations.name` |
| Codul fiscal | `organizations.idno` |
| Cod CAEM (4 cifre) | `organizations.caem` |
| Denumirea subdiviziunii SFS | `organizations.sfs_office` |
| Data prezentării | data generării |

## 2. Indicatori

Toate sumele vin din **contabilitatea financiară** (`entry_lines`), conform Indicațiilor metodice pentru ONG (Ordinul MF nr. 188/2014) și SNC.

| Cod | Indicator | Calcul / sursa |
|-----|-----------|----------------|
| **010** | Excedentul (deficitul) perioadei până la impozitare | `0101 − 0102` (cu semnul „−” la deficit) |
| **0101** | Total venituri (clasa „Venituri”) | `01011 + 01012 + 01013` |
| 01011 | Venituri aferente mijloacelor cu destinație specială (granturi, donații, alocații, asistență, contribuții ale fondatorilor condiționate de programe/proiecte) | venituri cu `activity_type = special_purpose` |
| 01012 | Venituri din activitatea economică prevăzută în statut | `activity_type = economic` |
| 01013 | Venituri aferente mijloacelor nepredestinate (contribuții ale membrilor, alte venituri neconditionate, **inclusiv desemnarea procentuală**) | `activity_type = other` |
| 01014 | *Informativ:* încasări din desemnarea procentuală în perioadă | venituri pe granturi cu `funding_type = percentage_designation` |
| **0102** | Total cheltuieli (clasa „Cheltuieli”) | `01021 + 01022 + 01023` |
| 01021 | Cheltuieli aferente mijloacelor cu destinație specială | cheltuieli `special_purpose` |
| 010211 | – din care utilizate **contrar destinației** (art. 52 alin.(2) lit. c)–d) CF) | cheltuieli `special_purpose` cu `is_non_statutory = true` |
| 01022 | Cheltuieli din activitatea economică prevăzută în statut | `economic` |
| 01023 | Alte cheltuieli (cu excepția celor din activitatea economică) | `other` |
| 010231 | – din care utilizate în scopuri **neprevăzute de statut** | `other` cu `is_non_statutory = true` |
| 01024 | *Informativ:* cheltuieli din mijloacele desemnării procentuale | cheltuieli pe granturi `percentage_designation` |
| 010241 | – din care **neutilizate** în scopul din pct. 27 HG 1286/2016 | idem, `is_non_statutory = true` |
| **020** | Suma spre impozitare | `010211 + 010231 + 010241` |
| **030** | Excedentul scutit de impozitare | `0101 − 0102 − 020`; dacă < 0 → `0` |
| **040** | Impozitul pe venit nesupus achitării | `030 × 050` |
| **050** | Cota impozitului pe venit, % | `tax_rates` cod `INCOME_TAX_LEGAL` valabil în an (12 în formular) |
| **060** | Total impozit pe venit spre plată | `020 × 050` |
| — | Suma de control | = rândul 060 |

> Formularul tipărit vechi are coduri diferite pentru unele rânduri; în aplicație se folosește **numerotarea din instrucțiunea modificată în 2025** (de mai sus). Formularul e o versiune în `report_forms` → la următoarea modificare se adaugă versiune nouă.

## 3. Anexa 1D — utilizarea sumelor din desemnarea procentuală

| Rând | Col.2 Perioada fiscală a desemnării | Col.3 Prima perioadă după | Col.4 A doua perioadă după | Col.5 Rămase la sfârșit (de restituit) |
|------|---|---|---|---|
| Sumele desemnate procentual (lei) | primite | X | X | X |
| Suma cheltuielilor TOTAL (lei) | utilizate | utilizate | utilizate | X |
| – activități de utilitate publică | … | … | … | X |
| – activități sociale, morale, culturale sau de caritate | … | … | … | X |
| – acoperirea cheltuielilor administrative | … | … | … | X |
| Sume rămase la sfârșitul perioadei | X | X | X | neutilizate în 2 ani → restituire la buget |

Sursa: granturi cu `funding_type = percentage_designation` (câte unul pentru fiecare an al desemnării), cheltuielile lor pe ani, grupate după `cost_items.designation_category` (utilitate publică / social-caritate / administrative).

## 4. Reguli de verificare

1. `0101 = 01011 + 01012 + 01013`; `0102 = 01021 + 01022 + 01023`; `010 = 0101 − 0102`.
2. `010211 ≤ 01021`; `010231 ≤ 01023`; `010241 ≤ 01024`.
3. `030 ≥ 0`.
4. Anexa 1D: o sumă desemnată neutilizată 2 ani după an → avertisment „de restituit până la termenul declarației”.
5. Totalurile 0101 și 0102 coincid cu soldurile claselor de venituri / cheltuieli din balanța anului.

## 5. Ce trebuie în date pentru ONG17

- fiecare cont de venituri/cheltuieli (sau fiecare înregistrare) știe tipul activității: **destinație specială / economică / altele**;
- cheltuielile se pot marca **„contrar destinației / neprevăzute de statut”**;
- granturile din **desemnarea procentuală** sunt marcate și au anul desemnării.
