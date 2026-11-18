# Analiza configurației 1C „Бухгалтерия для Молдовы + НКО, ред. 3.0” (v3.0.63.11)

Sursa: copia bazei de lucru (`1Cv8.1CD`), citită direct din tabela `CONFIG` cu biblioteca open-source `onec-dtools`, fără platforma 1C. Furnizor: Soft Lider SRL. Doar structura (nume de obiecte și câmpuri), fără codul sursă al furnizorului.

## Dimensiunea configurației

| Tip obiect | Număr | Ce preluăm în aplicația noastră |
|------------|------:|---------------------------------|
| Cataloage (Справочники) | 299 | ~30 utilizate efectiv de un ONG |
| Documente | 200 | ~25 pentru versiunea 1 |
| Registre de informații | 540 | majoritatea tehnice (BSP) — nu se preiau |
| Registre de acumulare | 77 | înlocuite de calcule din `entry_lines` |
| Plan de conturi | 1 (Хозрасчетный) | da → `accounts` |
| Registru contabil | 1 (Хозрасчетный, cu dimensiunea **НКО**) | da → `entry_lines` |
| Planuri de tipuri de calcul | 2 (Начисления, Удержания) | da → tipuri de calcul salarial |
| Registre de calcul | 2 (Начисления, Удержания) | da → `payroll_entries` |
| Enumerări | 507 | doar cele folosite |
| Rapoarte | 146 | ~10 |
| Module comune | 1307 | logica se rescrie, nu se copiază |

Concluzie: 1C conține mult funcțional pe care un ONG nu îl folosește (producție, leasing, comerț cu amănuntul, anvelope, taxi). Aplicația noastră păstrează doar ce trebuie, deci e mai simplă și mai rapidă.

## Partea specifică ONG (НКО) — de preluat obligatoriu

| Obiect 1C | Ce este | Tabela noastră |
|-----------|---------|----------------|
| Catalog `НКО_Проекты` | Proiecte / granturi | `grants` |
| Catalog `НКО_БюджетныеЛинии` | Linii de buget | `budget_lines` |
| Catalog `НазначениеЦелевыхСредств` | Destinația mijloacelor cu destinație specială | `grants` / sursă de finanțare |
| Catalog `Статьи5CON` | Articole pentru raportul 5-CON | `report_forms` (mapare articole) |
| Document `НКО_НачислениеЦелевыхСредств` | Înregistrarea finanțării primite | document nou `grant_income` |
| Document `НКО_РаспределениеЗатрат` | Repartizarea cheltuielilor pe proiecte | `allocations` |
| Raport `НКО_Статистический5CON` | 5-CON | `tax_reports` (form 5-CON) |
| Raport `НКО_ВедомостьПоПроектам` | Fișa pe proiecte | execuția bugetului |
| Raport `НКО_ЗадолженностьПоЦелевымСредствам` | Datoria privind mijloacele cu destinație specială | raport intern |
| Raport `НКО_ГодовойБаланс` | Bilanțul anual | raport standard |
| Registrul `Хозрасчетный`, dimensiunea `НКО` | Fiecare înregistrare Dt/Kt are proiectul | `entry_lines.grant_id`, `budget_line_id` |

## Documentele de bază pentru versiunea 1

| Secțiune | Documente 1C |
|----------|--------------|
| Bancă și casă | `ПлатежноеПоручение`, `ПоступлениеНаРасчетныйСчет`, `СписаниеСРасчетногоСчета`, `ПриходныйКассовыйОрдер`, `РасходныйКассовыйОрдер`, `АвансовыйОтчет` |
| Achiziții | `ПоступлениеТоваровУслуг`, `СчетФактураПолученный` (factura fiscală primită), `СчетНаОплатуПоставщика` |
| Vânzări | `РеализацияТоваровУслуг`, `СчетФактураВыданный`, `ОказаниеУслуг` |
| Mijloace fixe | `ПринятиеКУчетуОС`, `СписаниеОС`, `ПеремещениеОС`, `ПередачаМатериаловВЭксплуатацию` |
| Salarii și personal | `ПриемНаРаботу`, `Увольнение`, `КадровыйПеревод`, `НачислениеЗарплаты`, `Отпуск`, `БольничныйЛист`, `Премия`, `ВедомостьНаВыплатуЗарплаты*`, `ОтражениеЗарплатыВБухучете`, `ЗаявлениеНаПредоставлениеСтандартныхВычетовПоНДФЛ` (cererea de scutire) |
| Operațiuni | `ОперацияБух` (operațiune manuală), `ВводНачальныхОстатков`, `ЗакрытиеCчетов`, `РегламентнаяОперация` |
| Raportare | `РегламентированныйОтчет` (container pentru rapoartele fiscale), raportul `IPC18` |

## Cauza erorii cu scutirea (CIM vs contract civil) — confirmată în cod

- Cererea de scutire (`ЗаявлениеНаПредоставлениеСтандартныхВычетовПоНДФЛ`) are câmpurile `Сотрудник`, `КодВычетаЛичный`, `ВычетыНаДетей` — fără legătură cu tipul contractului.
- În modulul de calcul, dreptul la scutire se verifică prin indicatorul `ЕстьЛичноеОсвобождение`, calculat cu filtrul **„для физлица”** (pe persoana fizică), iar plafonul de venit care anulează dreptul la scutire se ia din registrul `ТарифыСтраховыхВзносов` (`СуммаНалогооблагаемогоДоходаЛишающаяПраваНаЛичноеОсвобождение`) și se compară cu **baza totală** a persoanei.
- Documentul `ПриемНаРаботу` are doar `ВидЗанятости` (de bază / cumul), nu și „contract civil”. Contractul civil se introduce ca o angajare cu alt tip de calcul, deci venitul lui intră în aceeași bază pe persoană.

Rezultat: venitul din contractul civil intră în baza pe care se aplică scutirea personală.

Formulele de calcul ale impozitelor sunt păstrate în 1C ca **date** (registrul `ФормулыРасчетаНалогов`, cu perioadă), nu în cod — aceeași idee ca tabela noastră `tax_rates`.

În aplicația noastră: scutirea se leagă de **contractul CIM de bază** (`contracts.is_main_job`), iar tipurile de venit (cod venit `КодДоходаНДФЛ` din 1C) se păstrează pe fiecare calcul. Contractul civil are alt cod de venit, la care scutirea nu se aplică.

## Planul de conturi și înregistrările

- Registrul `Хозрасчетный` are resursele `Сумма`, `ВалютнаяСумма`, `Количество`, `СуммаНУ` (contabilitate fiscală) și dimensiunile `Организация`, `Валюта`, `Подразделение`, **`НКО`**.
- Planul de conturi are atributele `Валютный`, `Количественный`, `УчетПоПодразделениям`, `НалоговыйУчет` și până la 3 subconto.
- Tabela noastră `entry_lines` trebuie extinsă cu: `department_id` (subdiviziune) și `tax_amount` (suma pentru contabilitatea fiscală, `СуммаНУ`).

## Proiecte ONG — detalii care au schimbat schema noastră

- `НКО_Проекты` are secțiunea tabelară **`Доноры`** (`Донор`, `ПроцентУчастия`, `Сумма`) → un proiect poate avea **mai mulți donatori** (cofinanțare). Am adăugat tabela `grant_donors`.
- Proiectul are `ВидФинансирования`, `Валюта`, `СчетПроекта`, `СуммаПроекта`, `Закрыт`, `НачислятьЗадолженностьПоФинансированию` → câmpuri noi în `grants`.
- `НКО_БюджетныеЛинии` are `СтатьяЗатрат` și `ВидПоступления` → linia de buget e legată de un **articol de cheltuieli**, iar articolul — de rândul din **5-CON**. Am adăugat `cost_items` cu `con5_article`.
- `НКО_РаспределениеЗатрат` repartizează un cont de cheltuieli pe proiecte cu `Кэффициент` și `МетодРаспределенияЗатрат` → repartizare automată pe coeficienți în `allocations`.

## Rapoartele fiscale

| Raport | Unde e în 1C |
|--------|--------------|
| **IPC21** | în raportul `IPC18` (formular cu versiuni; denumirea IPC21 apare în 7 module ale lui) |
| **5-CON** | raportul `НКО_Статистический5CON` + catalogul `Статьи5CON` |
| **ONG17** | **nu există** în configurație și nici în date — se completează în afara 1C; aplicația noastră îl adaugă ca funcție nouă |
| Alte | declarația TVA, BASS, declarația CNAM, REV, IALS, BIJ17, TL13 |

## Pașii următori

1. Migrarea: maparea tabelelor fizice ale bazei (`_Reference…`, `_Document…`, `_AccRg…`) la tabelele noastre — se pot citi direct din `1Cv8.1CD`, fără OData.
2. Structura celulelor din 5-CON → `report_forms.structure` (IPC21 — gata: [05-specificatie-IPC21.md](05-specificatie-IPC21.md)).

Lista completă a câmpurilor pentru obiectele preluate: [04-anexa-campuri-1c.md](04-anexa-campuri-1c.md).
