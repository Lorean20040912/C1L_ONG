# Sarcina tehnică (Terms of Reference) — Task 1

**Denumirea proiectului:** ContaHub — sistem web de contabilitate pentru ONG-uri, SRL-uri, întreprinderi individuale și gospodării țărănești din Republica Moldova, înlocuitor al 1C:Contabilitate, cu asistență AI
**Tip:** proiect examen „Programare Web 2” + teză de licență
**Autor:** Lorean Mândrescu
**Versiune:** 0.3 · noiembrie 2026

---

## 1. Context și problema

În organizație, mai mulți contabili (sub coordonarea contabilului-șef) țin evidența mai multor firme în 1C:Întreprindere 8.3: ONG-uri (configurația 1C:Contabilitate pentru ONG), SRL-uri (comerț cu bunuri de uz casnic, magazin alimentar cu fast-food, magazin alimentar plătitor de TVA, bază de odihnă), o întreprindere individuală (magazin alimentar) și o gospodărie țărănească (pomicultură). Logica de bază și interfața sunt cunoscute și funcționează, dar:

| # | Problema | Consecința |
|---|----------|-----------|
| P1 | Configurația nu deosebește **contractul individual de muncă (CIM)** de **contractul civil** — scutirea personală se aplică cumulat la ambele venituri. | Impozit pe venit calculat greșit. |
| P2 | Documentele primare stau pe Google Drive și se introduc manual a doua oară în 1C. | Muncă dublă, erori. |
| P3 | Rapoartele pentru donatori (Soros etc.) se completează manual în Excel, pe linii de buget. | Ore pierdute la fiecare raportare. |
| P4 | Cotele de impozit și plafoanele se schimbă anual; actualizarea depinde de furnizor. | Risc de calcul cu cota veche. |
| P5 | Integrarea 1C cu alte sisteme (CSV/DBF/TXT) este instabilă. | Automatizarea nu e posibilă. |
| P6 | 1C cere licențe per utilizator și instalare pe fiecare calculator / RDP. | Cost și administrare. |
| P7 | Pentru fiecare tip de firmă există altă configurație 1C, cu alte reguli și alte erori; contabilul trece între programe diferite. | Lucru fragmentat, întreținere dublă. |

## 2. Scopul proiectului

Crearea unui **sistem web de contabilitate care înlocuiește complet 1C** pentru ONG-uri, SRL-uri (inclusiv plătitori de TVA, comerț, alimentație publică, cazare), întreprinderi individuale și gospodării țărănești — **un singur nucleu comun și profiluri de funcționalitate** alese la crearea bazei (vezi [13-tipuri-entitati-profiluri.md](13-tipuri-entitati-profiluri.md)):
- **păstrează modul de lucru din 1C 8.3** (secțiuni, liste de documente, formulare, butoane „Înregistrează și închide”, „Dt/Kt”, rapoarte de tip balanță de verificare), ca contabilii să lucreze fără reinstruire;
- **păstrează logica contabilă** (planul de conturi, înregistrări contabile, regulile de calcul) cunoscută din configurația actuală, corectând erorile cunoscute;
- **preia toate datele existente din 1C** (cataloage, solduri, documente, istoricul înregistrărilor);
- adaugă ce 1C nu are: citirea automată a documentelor (OCR + AI), arhiva pe Google Drive pe linii de buget, rapoarte automate pentru donatori, monitorizarea legislației;
- rulează pe serverul organizației în **Docker**, accesat din browser de mai mulți contabili simultan.

## 3. Utilizatori și roluri

| Rol | Drepturi |
|-----|----------|
| **Administrator** | utilizatori, organizații, setări, backup |
| **Contabil-șef** | tot ce face contabilul + închiderea perioadei, aprobarea cotelor noi, interzicerea modificării perioadelor închise |
| **Contabil** | documente, înregistrări, salarii, rapoarte în organizațiile atribuite |
| **Manager de proiect** | vizualizează execuția bugetului grantului |
| **Auditor / Donator** | doar citire pentru un grant |

O instanță deservește **mai multe organizații**; fiecare contabil vede doar organizațiile atribuite.

## 4. Cerințe funcționale

### M00. Bazele și profilurile de funcționalitate
- F00.1 **Pagina de start „Bazele mele”** (ca lista de baze din 1C): bazele la care utilizatorul are acces, cu tipul firmei; butoanele „Bază nouă” și „Importă din 1C”.
- F00.2 **Expertul „Bază nouă”**: IDNO și date de identificare → forma juridică (SRL, SA, ÎI, GȚ, ONG) → plătitor de TVA (de la ce dată) → regimul fiscal propus automat → genurile de activitate (comerț cu amănuntul/ridicata, alimentație publică, producție, servicii, cazare, agricultură, granturi) → are salariați → sursa datelor (goală / 1C / Excel) → rezumatul modulelor care vor fi pornite.
- F00.3 La creare se aplică automat: planul de conturi potrivit (sau partida simplă pentru ÎI/GȚ), secțiunile și documentele interfeței, regulile de înregistrare, rapoartele din calendar, cotele și regimul fiscal.
- F00.4 **Administrare → Funcționalitate**: orice opțiune se poate schimba ulterior, cu data de la care se aplică (ex. devenirea plătitor de TVA).
- F00.5 Profilurile și legătura lor cu modulele sunt **date**, nu cod — un gen de activitate nou se adaugă fără programare.

### M0. Interfața de tip 1C 8.3
- F0.1 Panou de secțiuni în stânga, ca în „Бухгалтерия для Молдовы + НКО 3.0”: *Principal, Conducătorului, Bancă și casă, Vânzări, Achiziții, Depozit, Mijloace fixe și INM, Salarii și personal, Operațiuni, Rapoarte, Cataloage, Administrare, ONG*.
- F0.1a **Pagina inițială** cu calendarul obligațiilor de raportare pe organizație (ex. IPC21 lunar, 5-CON trimestrial, ONG17 anual): termen, raport, statut *Restanță / A rămas o săptămână / Prezentat*, cu deschiderea raportului dintr-un clic.
- F0.2 Fiecare document are **listă** (jurnal cu filtre, căutare, marcaj „înregistrat”) și **formular** (antet + tabel de rânduri + subsol cu totaluri).
- F0.3 Butoane standard: *Creare, Copiere, Înregistrare (postare), Anulare înregistrare, Înregistrează și închide, Marcare pentru ștergere, Dt/Kt (vizualizare înregistrări), Tipărire*.
- F0.4 Mai multe formulare deschise simultan, ca file (tab-uri); navigare din tastatură (Insert, F2, F8, Ctrl+Enter etc.).
- F0.5 Câmpuri de selecție din cataloage cu căutare rapidă; deschiderea elementului din câmp.
- F0.6 Aspectul este **inspirat** de 1C (paradigmă familiară), realizat cu componente proprii; nu se copiază resurse grafice sau cod al 1C.

### M1. Nucleul contabil
- F1.1 Planul de conturi conform Planului general de conturi contabile al RM, cu analitică (subconto) pe conturi.
- F1.2 Cataloage: organizații, contrapartide, contracte, persoane, conturi bancare, case, articole/servicii, mijloace fixe, unități de măsură, valute, surse de finanțare, granturi, linii de buget.
- F1.3 La **înregistrarea** unui document se generează automat înregistrări contabile (Dt/Kt) după reguli configurabile; anularea le șterge.
- F1.4 Operațiune manuală (înregistrări introduse direct).
- F1.5 Închiderea perioadei: după închidere documentele din perioadă nu pot fi modificate (doar de contabilul-șef).
- F1.6 Rapoarte standard: balanța de verificare (OSV), fișa contului, analiza contului, cartea mare, soldurile pe contrapartide, registrul documentelor.
- F1.7 Multi-valută, cu curs BNM descărcat automat.

### M2. Documente principale (versiunea 1)
Factură primită, factură emisă, ordin de plată (intrare/ieșire), extras bancar, dispoziție de încasare/plată (casă), avans spre decontare, act de prestări servicii, intrare/punere în funcțiune/amortizare mijloace fixe, calcul salariu, plata salariului, operațiune manuală.

### M2b. Mijloace fixe fără documente separate + închiderea lunii
- F2b.1 **O singură factură primită** poate conține rânduri de tipuri diferite: *mijloc fix*, *OMVSD* (obiecte de mică valoare și scurtă durată), *materiale*, *mărfuri*, *servicii*. Fiecare rând are tipul lui și contul implicit.
- F2b.2 La înregistrarea facturii, pentru rândurile *mijloc fix* se creează automat fișa mijlocului fix (denumire, nr. de inventar propus, valoare, grant) și se propune punerea în funcțiune la aceeași dată; durata de utilizare și metoda se iau din grupa/categoria aleasă.
- F2b.3 OMVSD: la înregistrare se poate alege „dare în exploatare imediată” (cu trecerea pe cheltuieli conform politicii contabile).
- F2b.4 **Asistentul „Închiderea lunii”**: o listă de pași cu statut (✓ / de făcut / eroare) — calculul amortizării, calculul salariului, repartizarea cheltuielilor pe granturi, diferențe de curs, recunoașterea veniturilor din mijloace cu destinație specială, închiderea conturilor, verificări (Dt=Kt, solduri negative, documente neînregistrate). Fiecare pas arată ce înregistrări va genera **înainte** de a le face; pașii se pot anula și reface.
- F2b.5 Amortizarea se calculează lunar automat (liniar, pe grupe), cu raportul de amortizare pe mijloace fixe și granturi.

### M2c. Schimbul cu banca (fișiere)
- F2c.1 **Import extras bancar** din fișierele pe care le dau băncile: **TXT, DBF, DBO** (și XML/CSV, dacă banca le oferă).
- F2c.2 **Export ordine de plată** în formatul băncii, pentru încărcare în sistemul bancar.
- F2c.3 Pentru fiecare bancă — un **profil de format** (codificare, separatori, maparea câmpurilor), configurat o dată; profiluri gata pentru băncile folosite de organizație.
- F2c.4 La import: recunoașterea contrapartidei după IDNO/IBAN, propunerea contului și a grantului, detectarea rândurilor deja importate (fără dubluri), crearea documentelor *Încasare pe cont* / *Plată din cont* ca ciorne.
- F2c.5 Jurnalul importurilor (fișier, bancă, câte rânduri, câte create / ignorate / cu erori).

### M2d. e-Factura (SFS) prin API
- F2d.1 Descărcarea automată a facturilor electronice primite din e-Factura → documente *Factură primită* completate (fără OCR).
- F2d.2 Trimiterea facturilor emise în e-Factura și urmărirea statutului (trimisă / semnată / acceptată / respinsă).
- F2d.3 Legătura documentului cu ID-ul din e-Factura; arhiva e-Factura în aplicație.
- F2d.4 Accesul la API se face cu datele/certificatul organizației, păstrate criptat; condițiile de conectare se clarifică cu SFS.

### M2e. Sursa documentelor: Google Drive sau folder local
- F2e.1 Fiecare organizație alege unde stau documentele originale: **Google Drive** (contul organizației sau al utilizatorului, prin OAuth) sau **folder local**.
- F2e.2 Folder local: (a) un folder de pe server / rețea, montat în Docker, sau (b) un folder de pe calculatorul utilizatorului, sincronizat printr-un **agent mic de sincronizare** instalat pe calculator (urcă fișierele noi și primește structura de foldere creată de aplicație).
- F2e.3 Restul aplicației lucrează la fel indiferent de sursă (stratul `storage` comun).

### M2a. Plăți către persoane fizice (nu salarii)
- F2a.1 Document „Plată către persoană fizică” pentru chirie (FOL), arendă teren agricol (PLs), servicii/contract civil (PL), donații (DON pf), dobânzi, royalty.
- F2a.2 Tipul plății determină codul sursei de venit IPC21 și cota de reținere (din `tax_rates`).
- F2a.3 Impozitul reținut ajunge automat în IPC21, cheltuiala — în 5-CON și pe linia de buget a grantului. Nu mai e nevoie de introducere manuală în IPC.

### M3. Salarizare (CIM vs contract civil)
- F3.1 Fiecare contract are tip explicit: `CIM` sau `contract_civil`.
- F3.2 Calculul se face **pe contract**: la CIM — contribuții CNAS, prima CNAM, impozit pe venit cu scutire personală / pentru persoane întreținute (doar la locul de muncă de bază); la contractul civil — reținere la sursă **fără scutire personală**.
- F3.3 Repartizarea cheltuielilor salariale pe granturi și linii de buget.
- F3.4 Fișe de salariu, statul de plată, date pentru IPC21 / IALS.

### M4. Cote și legislație
- F4.1 Toate cotele, plafoanele și scutirile stau în BD cu perioadă de valabilitate și temei legal.
- F4.2 Calculul folosește automat cota valabilă la data operațiunii.
- F4.3 Agentul AI monitorizează sursele oficiale (legis.md, sfs.md, cnas.md) și propune modificări; **contabilul-șef le aprobă**, nimic nu se aplică automat.

### M5. Documente scanate, Google Drive, AI
- F5.1 Conectare Google Drive (OAuth, doar folderele selectate); originalele rămân pe Drive, sortate automat `Organizație / An / Grant / Linie de buget / Tip`.
- F5.2 OCR + AI creează **documentul-ciornă** (factură, ordin de plată) cu câmpurile completate și nivel de încredere; contabilul verifică side-by-side și înregistrează.
- F5.3 Import direct e-Factura (SFS) fără OCR.
- F5.4 Detectarea dublurilor (hash) și propunerea automată a grantului / liniei de buget.

### M6. Granturi și rapoarte pentru donatori
- F6.1 Donatori, granturi, linii de buget, alocarea cheltuielilor (din documente și salarii).
- F6.2 Execuția bugetului: planificat / cheltuit / rest, alertă la depășire.
- F6.3 Încărcarea **oricărui** șablon Excel al donatorului (fiecare donator are alt șablon); AI-ul recunoaște structura (foi, tabele, rânduri pe linii de buget, celule de total) și propune maparea; contabilul o confirmă o dată, apoi șablonul se reutilizează.
- F6.4 **Cerințele donatorului**: pentru fiecare donator/grant contabilul scrie, în cuvinte simple, ce documente justificative cere donatorul (ex. „pentru deplasări: ordin, bilete, decont, raport de deplasare; pentru salarii: contract, foaie de pontaj, stat de plată”). AI-ul transformă instrucțiunea în reguli și le aplică.
- F6.5 **Pachetul de raportare** — un singur buton generează:
  - folderul `Rapoarte / <Donator> / <Grant> / <Perioada>`;
  - raportul Excel completat în șablonul donatorului;
  - subfoldere **pe linii de buget**, cu copiile/linkurile documentelor justificative selectate de AI după cerințele donatorului;
  - o listă de verificare: ce documente lipsesc pentru fiecare cheltuială.
- F6.6 Operatorii pot lucra și manual în structura de foldere a donatorului (să adauge documente pe linii de buget); aplicația le recunoaște și le leagă de cheltuieli.

### M6a. Rapoarte fiscale și statistice
- F6a.1 **IPC21** (lunar, SFS) — darea de seamă privind reținerea impozitului pe venit, a contribuțiilor CNAS și a primelor CNAM, completată automat din salarizare, cu anexele pe persoane și pe tip de venit (CIM / contract civil separat).
- F6a.2 **5-CON** (trimestrial, BNS) — cheltuielile și costurile organizațiilor necomerciale, completat din înregistrările contabile pe articole de cheltuieli.
- F6a.3 **ONG17** (anual, SFS) — declarația organizației necomerciale, completată din datele anului, inclusiv anexa 1D (desemnarea procentuală). Lipsește în 1C actual — funcție nouă.
- Specificații detaliate: [IPC21](05-specificatie-IPC21.md), [ONG17](06-specificatie-ONG17.md), [5-CON](07-specificatie-5CON.md).
- F6a.4 Fiecare raport: completare automată → verificare și corectare manuală a celulelor → salvare versiune → export în formatul acceptat de **e-Cabinet SFS** / portalul BNS (XML/XLS) și tipărire PDF.
- F6a.5 Formularele de raport sunt descrise ca **șabloane cu versiune și perioadă de valabilitate** (când SFS/BNS schimbă formularul, se adaugă o versiune nouă; rapoartele vechi rămân pe forma veche).
- F6a.6 Descifrarea fiecărei cifre: clic pe celulă → lista înregistrărilor/documentelor din care provine.

### M8. Asistentul AI
- F8.1 **Chat** cu asistentul, disponibil din orice ecran (panou lateral); știe pe ce ecran/document este utilizatorul.
- F8.2 Poate: explica o operațiune, găsi documente și sume, propune înregistrări contabile, completa un document-ciornă, pregăti un raport, crea pachetul pentru donator, căuta **pe internet** (legislație, practici contabile, cazuri excepționale) și da sursele (link).
- F8.3 **Nimic nu se aplică fără confirmare**: asistentul creează *propuneri* (document-ciornă, înregistrare propusă, modificare de setare) pe care utilizatorul le acceptă sau le respinge. Asistentul are exact drepturile utilizatorului care îl folosește.
- F8.4 **Personalizarea interfeței prin chat**: utilizatorul scrie „mută butonul X lângă Y”, „redenumește coloana”, „ascunde câmpul”, „pune implicit contul 713” — asistentul modifică **setările de interfață** (nu codul): textul etichetelor, ordinea și vizibilitatea câmpurilor/coloanelor/butoanelor, valori implicite. Modificarea se vede imediat, poate fi anulată, are istoric; la nivel de organizație o aprobă contabilul-șef.
- F8.5 Memorie de organizație: regulile explicate asistentului („la noi chiria se pune pe linia 3.4”) se salvează și se folosesc data viitoare; pot fi văzute și șterse.
- F8.6 Toate conversațiile și acțiunile asistentului sunt în jurnalul de audit.

### M11. Stocuri, comerț, alimentație publică, TVA (profil SRL)
- F11.1 **Nomenclator** (mărfuri, materiale, produse, servicii), **depozite**, intrări / ieșiri / transferuri / inventariere; metoda de evaluare a stocurilor din politica contabilă (FIFO / cost mediu ponderat).
- F11.2 **Comerț cu amănuntul**: case de marcat, raportul Z / vânzarea cu amănuntul pe zi, adaos comercial, descărcarea stocului la vânzare.
- F11.3 **Alimentație publică / fast-food**: **rețete și fișe de calculație** (ingrediente, cantități, pierderi tehnologice); la vânzarea unui produs se descarcă automat materia primă; calculul costului.
- F11.4 **TVA**: facturi fiscale emise/primite, e-Factura, registrele de cumpărări și vânzări, TVA deductibil / nedeductibil, TVA la importul de servicii, **declarația TVA**.
- F11.5 **Cazare** (bază de odihnă): servicii de cazare și alimentație, unități de cazare, taxa locală pentru unitățile de cazare.

### M12. Întreprindere individuală (partidă simplă)
- F12.1 Aceleași documente primare, dar înregistrare în **partidă simplă**: venit = încasare, cheltuială = plată, cu categoria deductibilă / nedeductibilă.
- F12.2 **Registrul-jurnal de venituri și cheltuieli**, registrul mijloacelor fixe, lista de inventar — generate automat.
- F12.3 Declarația pe venit a ÎI, completată din registru; trecerea la partidă dublă cu solduri de deschidere, la nevoie.

### M13. Gospodărie țărănească
- F13.1 **Membrii GȚ** și cotele lor; distribuirea venitului rămas după impozitare, cu reținerea impozitului la distribuire.
- F13.2 **Producția agricolă**: livezi / culturi (suprafață, an de plantare), recolta, consumul de materiale și lucrări pe culturi, costul producției.
- F13.3 Impozitul specific GȚ (cota din `tax_rates`, cu perioadă) și darea de seamă **UNIF25** (secțiunea GȚ) / VEN12.

### M14. Asistentul de procese: sarcini și amintiri pentru toată contabilitatea
- F14.1 Pe lângă rapoarte, aplicația ține **toate procesele lunare** ale fiecărei firme ca sarcini recurente, de exemplu:
  - până pe 5: trimite administratorilor lista impozitelor de achitat;
  - la început de lună: scanează facturile lunii și pune-le în folderul lunii;
  - descarcă extrasul bancar și pune-l în folder / importă-l;
  - achită lumina, internetul, chiria pentru firma X;
  - închiderea lunii, calculul salariilor, inventarierea anuală.
- F14.2 **Folderele lunii se creează singure** pe 1 ale lunii în sursa de documente (Drive / folder local): `Contabilitate / <Firma> / <AAAA-LL> / Facturi`, `/ Bancă`, `/ Salarii`, `/ Altele`.
- F14.3 **Asistentul analizează contabilitatea și propune sarcini**: plăți care se repetă lunar (ex. aceeași factură de energie în fiecare lună), extrase bancare lipsă pentru luna curentă, documente scanate necontabilizate, rapoarte cu termen apropiat. Propunerea devine sarcină doar după confirmare.
- F14.4 Fiecare sarcină poate avea o **acțiune** dintr-un clic: deschide importul bancar, deschide folderul, pregătește ordinul de plată, generează mesajul pentru administrator.
- F14.5 **Mesaje către administratori**: aplicația calculează sumele (impozite, contribuții, termene) și pregătește textul; utilizatorul îl verifică și apasă „Trimite” (Telegram, Viber, e-mail) sau îl copiază. **Niciun mesaj nu pleacă fără confirmarea utilizatorului.**
- F14.6 Amintirile apar pe pagina inițială, ca notificare în aplicație și, la alegere, în Telegram / e-mail; fiecare utilizator își alege canalele și ora.

### M15. Evidența personală a utilizatorului (privată)
- F15.1 Contabilul care lucrează (cu salariu) la mai multe firme își poate lega profilul de persoana lui din fiecare bază.
- F15.2 La intrare, aplicația verifică **automat** în salariile și plățile fiecărei firme dacă salariul lunii a fost calculat și plătit, și îi amintește: „Octombrie: ✓ AO CARTERA, ✗ „Casa Bună” SRL — salariul nu a fost plătit”.
- F15.3 Funcția și datele ei sunt **vizibile doar utilizatorului respectiv** — nici administratorul, nici ceilalți contabili nu le văd; verificarea folosește doar datele la care utilizatorul are deja acces.
- F15.4 Utilizatorul își poate adăuga și amintiri personale proprii (private), separate de sarcinile firmelor.

### M9. Importul bugetului proiectului din fișier
- F9.1 La câștigarea proiectului, contabilul încarcă **bugetul aprobat** (Excel, de regulă în formatul donatorului; și PDF/Word).
- F9.2 AI-ul recunoaște structura: categorii și **linii de buget** (cod, denumire, unitate, cantitate, cost unitar, total), **contribuția donatorului / cofinanțarea / contribuția proprie**, valuta, perioada, **graficul tranșelor** (date și sume), după caz bugetul pe ani sau pe luni.
- F9.3 Ecran de previzualizare: rândurile recunoscute, totalurile verificate cu totalul din fișier, câmpurile nesigure evidențiate; contabilul corectează și confirmă.
- F9.4 La confirmare se creează automat: grantul (dacă nu există), liniile de buget ierarhice, legătura cu articolele de cheltuieli / 5-CON (propusă de AI), donatorii și cotele de cofinanțare, **graficul tranșelor**, iar — după politica contabilă — înregistrarea recunoașterii grantului (Dt 234.4/235 — Kt 425/537) pe sumă totală sau pe etape.
- F9.5 **Modificările de buget** (realocări aprobate de donator) se importă la fel, ca versiune nouă a bugetului; execuția se compară mereu cu versiunea în vigoare, iar istoricul versiunilor se păstrează.
- F9.6 Același șablon de donator se reține: la următorul proiect al aceluiași donator recunoașterea e instantanee.

### M10. Îmbunătățirea continuă prin asistent (versiuni beta)
- F10.1 Din orice ecran, utilizatorul poate scrie asistentului: „aici e o eroare”, „aș vrea ca…”, cu captură de ecran atașată automat → se creează o **cerere de modificare**.
- F10.2 Asistentul clasifică cererea:
  - **modificare de configurare** (interfață, texte, formule contabile, șabloane de rapoarte, reguli) → se face imediat ca **variantă beta** a setării, vizibilă doar pentru cine o testează;
  - **modificare de cod** (funcție nouă, eroare în logică) → asistentul pregătește modificarea pe o **ramură separată** a codului, cu teste, iar aplicația o instalează ca **versiune beta** separată.
- F10.3 Versiunea beta se testează o perioadă (utilizatorul alege cine o folosește: doar el / un grup / toți).
- F10.4 Utilizatorul decide: **„Promovează”** → devine versiunea de bază (actualizare pentru toți), sau **„Renunță”** → beta se șterge, nimic nu se schimbă în versiunea stabilă.
- F10.5 Nicio modificare nu ajunge în versiunea stabilă fără: testele automate trecute (inclusiv reconcilierea cu 1C și rapoartele IPC21 / 5-CON / ONG17), aprobarea contabilului-șef/administratorului și posibilitatea de întoarcere la versiunea anterioară.
- F10.6 Istoricul versiunilor și al cererilor e vizibil în aplicație („ce s-a schimbat”), iar la vânzarea către alte organizații, actualizările stabile ajung la ele ca release-uri.

### M7. Migrarea datelor din 1C
- F7.1 Import din 1C prin **interfața OData standard** a bazei 1C sau prin export XML (prelucrarea universală de export/import date XML).
- F7.2 Se importă: planul de conturi, cataloagele, soldurile inițiale la data trecerii, documentele și înregistrările contabile istorice (perioada aleasă).
- F7.3 Fiecare obiect importat păstrează GUID-ul din 1C → importul poate fi repetat fără dubluri.
- F7.4 Raport de reconciliere după import: balanța de verificare din aplicație = balanța din 1C, pe fiecare cont.
- F7.5 Perioadă de lucru în paralel 1C + aplicație până la confirmarea corectitudinii.

## 5. Cerințe nefuncționale

| Cod | Cerință |
|-----|---------|
| NF1 Securitate | HTTPS, parole Argon2, 2FA (TOTP), sesiuni cu expirare, roluri (RBAC), izolarea datelor pe organizație. |
| NF2 Audit | Orice modificare în `audit_log` (cine, ce, când, valoare veche/nouă); documentele înregistrate nu se șterg fizic, doar se marchează. |
| NF3 Integritate contabilă | Înregistrarea unui document și generarea înregistrărilor se fac într-o singură tranzacție BD; suma Dt = suma Kt verificată de BD. |
| NF4 Lucru simultan | 10+ contabili simultan; blocarea optimistă a documentului deschis de altcineva. |
| NF5 Date personale | Legea 133/2011: IDNP și IBAN criptate, acces minim necesar. |
| NF6 Stabilitate | Sarcinile grele (OCR, AI, import, rapoarte mari) în coadă cu reîncercări; backup automat zilnic BD. |
| NF7 Performanță | Liste și formulare < 1 s; balanța de verificare pe un an < 3 s. |
| NF8 Instalare | `docker compose up` pe server; actualizare fără pierderea datelor (migrări BD). |
| NF9 Limbă | Interfață în română și rusă (comutabilă per utilizator), ca în 1C. |

## 6. Stack tehnologic

| Strat | Tehnologie |
|-------|-----------|
| Frontend | React + TypeScript + Vite; tabele AG Grid / TanStack Table; UI cu tab-uri tip 1C |
| Backend | Python 3.12 + FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| Bază de date | PostgreSQL 16 |
| Cozi | Redis + worker |
| OCR / AI | Azure Document Intelligence + LLM (Claude) |
| Fișiere | Google Drive API sau folder local (montat în Docker / agent de sincronizare) |
| Bancă | parsere TXT / DBF (`dbfread`) / DBO pe profiluri de format |
| e-Factura | client API SFS |
| Asistent AI | Claude API cu instrumente (tool use): acces la API-ul aplicației cu drepturile utilizatorului + căutare web |
| Excel / PDF | openpyxl, WeasyPrint (formulare tipărite) |
| Import 1C | OData REST / XML |
| Infrastructură | Docker Compose (nginx, api, worker, postgres, redis), GitHub + GitHub Actions |

## 7. Etape și livrabile

| Etapă | Conținut |
|-------|----------|
| E1 | ToR, arhitectură, schema BD (dbdiagram.io), analiza configurației 1C |
| E2 | Autentificare, roluri, organizații, audit, Docker |
| E3 | Interfața de tip 1C (secțiuni, liste, formulare, tab-uri) |
| E4 | Nucleul contabil: plan de conturi, cataloage, înregistrări, OSV, fișa contului |
| E5 | Migrarea din 1C + reconcilierea balanței |
| E6 | Documentele bancă/casă/achiziții/vânzări cu reguli de înregistrare |
| E7 | Salarizare CIM / contract civil + cote cu valabilitate |
| E8 | Drive / folder local + OCR/AI pentru facturi și ordine de plată; schimb cu banca (TXT/DBF/DBO); e-Factura |
| E8a | Mijloace fixe din factură + asistentul „Închiderea lunii” |
| E8b | Asistentul AI (chat, propuneri, căutare pe internet, personalizarea interfeței) |
| E9a | Importul bugetului din Excel (linii, cofinanțare, tranșe, versiuni de buget) |
| E9b | Îmbunătățirea prin asistent: cereri de modificare, versiuni beta, promovare / renunțare |
| E9 | Granturi, execuția bugetului, rapoarte donatori pe șabloane oricare + pachetul de documente pe linii de buget |
| E10 | Rapoarte fiscale IPC21, 5-CON, ONG17 + calendarul raportărilor |
| E11 | Monitor legislativ, testare, documentare, susținere |
| E12 | Expertul „Bază nouă” și profilurile de funcționalitate |
| E13 | Profil SRL: stocuri, casă de marcat, TVA, rețete pentru alimentație publică (după susținere: cazare) |
| E14 | Profil ÎI (partidă simplă) și GȚ (membri, producție agricolă, UNIF25) — dezvoltarea produsului după susținere |
| E15 | Asistentul de procese (sarcini recurente, foldere lunare, mesaje către administratori) și evidența personală privată |

## 8. Criterii de acceptare

1. După migrare, balanța de verificare din aplicație coincide cu balanța din 1C pe toate conturile, la aceeași dată.
2. Un contabil care lucrează în 1C 8.3 poate introduce și înregistra o factură primită fără instruire suplimentară.
3. Pentru o persoană cu CIM și contract civil în aceeași lună, scutirea personală se aplică doar venitului din CIM.
4. Schimbarea unei cote cu dată de intrare în vigoare nu modifică lunile anterioare.
5. O factură scanată pusă pe Drive devine document-ciornă completat; după verificare se înregistrează cu înregistrările corecte.
6. Raportul financiar al donatorului se generează din șablonul lui, cu totaluri egale cu execuția bugetului.
7. Un utilizator nu vede datele organizațiilor neatribuite (test automat).
8. Documentele dintr-o perioadă închisă nu pot fi modificate de un contabil obișnuit.
9. IPC21, 5-CON și ONG17 generate pentru o perioadă de test coincid cifră cu cifră cu cele generate de 1C pentru aceeași perioadă.
10. Un extras bancar TXT/DBF importat de două ori nu creează plăți dublate.
11. O factură cu un mijloc fix, OMVSD și materiale se introduce o singură dată; mijlocul fix apare în fișa mijloacelor fixe și se amortizează la închiderea lunii.
12. Pentru un donator cu șablon Excel nou și cerințe scrise în cuvinte, aplicația generează raportul completat și folderele pe linii de buget cu documentele cerute.
13. O cerere în chat „mută butonul Dt/Kt la începutul barei” schimbă interfața imediat și poate fi anulată.
14. Bugetul unui proiect încărcat din Excel creează liniile de buget și tranșele cu totalurile egale cu fișierul, fără introducere manuală.
15. O cerere de modificare făcută prin asistent ajunge într-o versiune beta, iar la „Renunță” versiunea stabilă rămâne neschimbată.
16. La crearea unei baze pentru un SRL plătitor de TVA cu comerț cu amănuntul se pornesc automat stocurile, casele de marcat, TVA și declarația TVA în calendar, iar secțiunea ONG nu apare.
17. Pentru o ÎI, aceleași documente de plată generează registrul-jurnal de venituri și cheltuieli fără înregistrări Dt/Kt.
18. Pe 1 ale lunii, folderele lunii se creează singure, iar pe pagina inițială apar sarcinile lunii pentru fiecare firmă.
19. Mesajul cu impozitele pentru administrator se trimite doar după ce utilizatorul apasă „Trimite”.
20. Amintirea despre salariul personal apare doar în profilul utilizatorului; un alt utilizator (inclusiv administratorul) nu o vede.

## 9. În afara scopului (versiunea 1)

- Depunerea directă a rapoartelor (semnare electronică și trimitere) — aplicația generează fișierul, depunerea se face pe e-Cabinet SFS / portalul BNS.
- Rapoartele fiscale în afara celor din M6a (TVA, situații financiare complete etc.) — versiunea 2.
- Contabilitatea stocurilor complexă (producție, mai multe depozite cu costuri FIFO avansate).
- Aplicație mobilă nativă; plăți bancare inițiate din aplicație.
