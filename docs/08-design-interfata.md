# Designul interfeței

**Principiu:** un contabil care lucrează în 1C 8.3 („Taxi”) deschide aplicația și știe unde să apese. Păstrăm **paradigma** 1C (secțiuni → jurnale → formulare → Dt/Kt → rapoarte), dar desenăm totul cu componente proprii, fără resursele grafice ale 1C.

Prototip clicabil: [`design/prototip.html`](../design/prototip.html) — se deschide direct în browser.

## 1. Scheletul ecranului

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ ☰  ContaHub ONG   [AO „CARTERA” ▾]        🔍 Căutare (Ctrl+F)   🔔  ⏱  ☆  Utilizator │  bara de sus
├──────────────┬─────────────────────────────────────────────────────────────────┤
│ Principal    │ [Pagina inițială] [Facturi primite ×] [Factura 15 ×]             │  file (tab-uri)
│ Conducătorului├─────────────────────────────────────────────────────────────────┤
│ Bancă și casă│ ← →  Titlul formularului                               ⋮        │
│ Achiziții    │ [Înregistrează și închide] [Înregistrează] [Dt/Kt] [Tipărire ▾]  │  bara de comenzi
│ Vânzări      │                                                                 │
│ Salarii      │                    conținutul formularului                      │
│ Mijloace fixe│                                                                 │
│ Granturi/ONG │                                                                 │
│ Operațiuni   │                                                                 │
│ Rapoarte     │                                                                 │
│ Cataloage    │                                                                 │
│ Administrare │                                                                 │
└──────────────┴─────────────────────────────────────────────────────────────────┘
```

- **Panoul de secțiuni** (stânga, fundal cald deschis): click → se deschide **panoul de navigare** al secțiunii (documente / jurnale / rapoarte / cataloage ale secțiunii), ca în 1C.
- **File**: fiecare listă sau document se deschide într-o filă nouă; mai multe documente deschise simultan; filă cu modificări nesalvate are „*”.
- **Organizația curentă** se alege sus — toate listele și rapoartele sunt filtrate după ea.

## 2. Tipuri de ecrane

| Tip | Ce conține | Exemplu |
|-----|-----------|---------|
| **Pagina inițială** | calendarul raportărilor (IPC21, 5-CON, ONG17…) cu statut *Restanță / A rămas o săptămână / Prezentat*; documente scanate care așteaptă verificare; execuția bugetelor | după login |
| **Panoul secțiunii** | linkuri grupate: Documente, Jurnale, Rapoarte, Cataloage, Servicii | Achiziții |
| **Listă (jurnal)** | bara de comenzi, filtru perioadă, căutare, tabel virtualizat; iconiță: ✓ înregistrat, ○ neînregistrat, ✕ marcat pentru ștergere | Facturi primite |
| **Formular document** | antet (nr., dată, organizație, contrapartidă, contract), file interne (Mărfuri / Servicii / Grant), tabel editabil, subsol cu totaluri, comentariu, responsabil | Factură primită |
| **Formular cu scan (AI)** | stânga — documentul scanat de pe Drive; dreapta — câmpurile extrase; câmpurile cu încredere mică sunt evidențiate galben | Verificare document |
| **Dt/Kt** | tabelul înregistrărilor generate de document | din orice document |
| **Raport** | parametri (perioadă, organizație) → „Generează”; celulele se pot descifra (click → documentele sursă); Export XML / Excel / PDF | IPC21, 5-CON, OSV |
| **Catalog** | listă ierarhică (grupe) + formular element | Contrapartide |

## 3. Comenzi și taste (ca în 1C)

| Tastă | Acțiune |
|-------|---------|
| `Insert` | creare element / rând nou |
| `F9` | copiere |
| `F2` / `Enter` | deschidere / editare |
| `Ctrl+Enter` | înregistrează și închide |
| `Ctrl+S` | salvează |
| `F8` | selectare din catalog în câmp |
| `Delete` | marcare pentru ștergere |
| `Ctrl+F` | căutare în listă |
| `Esc` | închide fila / anulează |
| `Ctrl+Tab` | următoarea filă |

## 4. Stil vizual

| Element | Valoare |
|---------|---------|
| Font | sistem (Segoe UI / Arial), 13 px în tabele, 14 px în formulare |
| Panou secțiuni | fundal `#FBF3D5`, text `#333`, element activ `#F3DE8A` |
| Bara de sus | `#F7E7A6` |
| Buton principal | galben `#F5D34B`, text închis, bold — „Înregistrează și închide”, „Generează” |
| Buton secundar | alb cu bordură gri `#C8C8C8` |
| Linkuri | albastru `#2B5DA8`, subliniate (ca în 1C) |
| Titluri de grup | verde `#3C8D40` (ca titlurile de pe pagina inițială 1C) |
| Restanță / eroare | roșu `#C0392B` |
| Câmp de verificat (AI) | fundal `#FFF3B0`, bordură `#E0B400` |
| Rând selectat în tabel | `#FCEFB4` |

Densitatea e mare (ca în 1C): rânduri de tabel de 26 px, fără spații decorative mari — contabilul vede multe rânduri deodată.

## 5. Formulare generate din metadate

Fiecare tip de document/catalog are o **descriere în metadate** (JSON pe server): câmpurile antetului, tabelele, tipurile, cataloagele de selecție, coloanele listei. Frontend-ul are componente generice: `ListForm`, `ObjectForm`, `FieldInput`, `RefField` (câmp cu selecție din catalog), `TablePart`. Un document nou = o descriere nouă + o regulă de înregistrare în backend, fără a desena formular de la zero — exact ideea din 1C.

## 6. Accesibilitate și lucru zilnic

- totul se poate face din tastatură; focusul vizibil;
- formularele țin minte ultima organizație / contrapartidă folosită;
- validarea apare lângă câmp, nu în ferestre modale;
- lista ține minte filtrul și sortarea per utilizator;
- interfața în română și rusă (comutare per utilizator).
