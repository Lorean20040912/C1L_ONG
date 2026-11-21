// Secțiunile din stânga și panourile lor de navigare (după design/prototip.html).
// Linkurile sunt deocamdată doar navigare: ecranele vin odată cu modulele lor.

export interface Section {
  id: string;
  icon: string;
  title: string;
  groups?: Record<string, string[]>;
}

export const SECTIONS: Section[] = [
  { id: "home", icon: "≡", title: "Principal" },
  { id: "head", icon: "↗", title: "Conducătorului" },
  {
    id: "bank",
    icon: "₿",
    title: "Bancă și casă",
    groups: {
      Documente: ["Ordine de plată", "Încasări pe cont", "Plăți din cont", "Încasări numerar", "Plăți numerar", "Decont de avans"],
      Servicii: ["Import extras bancar", "Export ordine de plată", "e-Factura", "Curs BNM"],
    },
  },
  { id: "sales", icon: "⬆", title: "Vânzări" },
  {
    id: "purch",
    icon: "⬇",
    title: "Achiziții",
    groups: {
      Documente: ["Facturi primite", "Plăți către persoane fizice", "Servicii primite (acte)"],
      Jurnale: ["Documente scanate (AI)", "Facturi fiscale primite"],
      Rapoarte: ["Datorii față de furnizori", "Achiziții pe granturi"],
    },
  },
  { id: "stock", icon: "▦", title: "Depozit" },
  {
    id: "fa",
    icon: "▣",
    title: "Mijloace fixe și INM",
    groups: {
      Documente: ["Mijloace fixe (din factură)", "Punere în funcțiune", "Casare"],
      Servicii: ["Închiderea lunii"],
      Rapoarte: ["Fișa mijloacelor fixe", "Amortizarea pe granturi"],
    },
  },
  {
    id: "pay",
    icon: "👤",
    title: "Salarii și personal",
    groups: {
      Documente: ["Angajare", "Calcul salariu", "Plată către persoană fizică", "Contracte civile", "Cereri de scutire"],
      Rapoarte: ["Stat de plată", "Fișa de salariu", "IPC21"],
      Cataloage: ["Persoane fizice", "Tipuri de calcul"],
    },
  },
  {
    id: "ngo",
    icon: "♡",
    title: "Granturi și ONG",
    groups: {
      Granturi: ["Proiecte / granturi", "Linii de buget", "Donatori"],
      Documente: ["Finanțare primită", "Repartizarea cheltuielilor"],
      Rapoarte: ["Execuția bugetului", "Pachet pentru donator", "5-CON", "ONG17"],
      Setări: ["Articole de cheltuieli", "Date pentru rapoarte"],
    },
  },
  {
    id: "ops",
    icon: "Dt",
    title: "Operațiuni",
    groups: {
      Servicii: ["Închiderea lunii", "Operațiune manuală", "Ajustarea perioadei"],
      Rapoarte: ["Verificarea contabilității"],
    },
  },
  {
    id: "rep",
    icon: "▥",
    title: "Rapoarte",
    groups: {
      Standard: ["Balanța de verificare (OSV)", "Fișa contului", "Analiza contului", "Cartea mare", "Registru-jurnal (partidă simplă)"],
      Fiscale: ["IPC21", "ONG17", "TVA"],
      Statistice: ["5-CON"],
      Setări: ["Date pentru rapoarte"],
    },
  },
  {
    id: "cat",
    icon: "☰",
    title: "Cataloage",
    groups: { Contabilitate: ["Planul de conturi", "Contrapartide", "Subdiviziuni", "Articole de cheltuieli"] },
  },
  {
    id: "adm",
    icon: "⚙",
    title: "Administrare",
    groups: {
      Contabilitate: ["Politica contabilă", "Reguli de înregistrare", "Perioade închise", "Conturi bancare"],
      Utilizatori: ["Utilizatori și drepturi"],
      Setări: ["Surse de documente (Drive / folder)", "Profiluri bănci", "Funcționalitate"],
    },
  },
];
