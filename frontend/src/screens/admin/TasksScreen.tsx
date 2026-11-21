import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { day } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "./Messages";

interface Task {
  id: string;
  title: string;
  due_date: string;
  status: string;
  is_private: boolean;
  calendar_id: string | null;
  days_left: number;
}
interface Template {
  id: string;
  title: string;
  recurrence: string;
  is_active: boolean | null;
  standard: boolean;
}

const STATUS_LABEL: Record<string, string> = { open: "deschisă", overdue: "restantă", done: "îndeplinită", skipped: "omisă" };

/** Sarcini și termene: termenele din calendarul raportărilor, sarcinile lunii din șabloane, sarcini proprii. */
export function TasksScreen() {
  const { orgId, role } = useShell();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [showClosed, setShowClosed] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [tplTitle, setTplTitle] = useState("");
  const [tplRule, setTplRule] = useState("FREQ=MONTHLY;BYMONTHDAY=5");
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}`;
  const canEdit = can(role, POSTING_ROLES);
  const canTemplates = can(role, ADMIN_ROLES);

  const load = useCallback(async () => {
    setTasks(await api<Task[]>(`${base}/tasks`));
    setTemplates(await api<Template[]>(`${base}/task-templates`));
  }, [base]);
  useEffect(() => {
    load();
  }, [load]);

  const act = (id: string, what: "done" | "skip" | "reopen") =>
    run(async () => {
      await api(`${base}/tasks/${id}/${what}`, { method: "POST" });
      await load();
    });

  const add = () =>
    run(async () => {
      await api(`${base}/tasks`, { method: "POST", body: { title: title.trim(), due_date: due } });
      setTitle("");
      setDue("");
      await load();
    });

  const syncCalendar = () =>
    run(async () => {
      const created = await api<Task[]>(`${base}/tasks/sync-calendar`, { method: "POST" });
      await load();
      return created.length ? `Sarcini noi din calendarul raportărilor: ${created.length}.` : "Calendarul este la zi.";
    });

  const generate = () =>
    run(async () => {
      const created = await api<Task[]>(`${base}/tasks/generate`, { method: "POST", body: {} });
      await load();
      return created.length ? `Sarcini noi din șabloane: ${created.length}.` : "Sarcinile lunii există deja.";
    });

  const addTemplate = () =>
    run(async () => {
      await api(`${base}/task-templates`, { method: "POST", body: { title: tplTitle.trim(), recurrence: tplRule } });
      setTplTitle("");
      await load();
    });

  const removeTemplate = (id: string) =>
    run(async () => {
      await api(`${base}/task-templates/${id}`, { method: "DELETE" });
      await load();
    });

  const visible = tasks.filter((t) => showClosed || t.status === "open" || t.status === "overdue");

  return (
    <>
      <h1>Sarcini și termene</h1>
      <Messages error={error} info={info} />
      <div className="bar">
        {canEdit && (
          <>
            <button className="b" onClick={syncCalendar} disabled={busy}>
              Termene din calendarul raportărilor
            </button>
            <button className="b" onClick={generate} disabled={busy}>
              Sarcinile lunii din șabloane
            </button>
          </>
        )}
        <label>
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> arată și cele închise
        </label>
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>Termen</th>
            <th>Sarcina</th>
            <th>Stare</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {visible.map((t) => (
            <tr key={t.id}>
              <td>{day(t.due_date)}</td>
              <td>
                {t.title}
                {t.is_private && " 🔒"}
              </td>
              <td className={t.status === "overdue" ? "late" : t.status === "done" ? "ok" : undefined}>{STATUS_LABEL[t.status] ?? t.status}</td>
              <td>
                {canEdit && (t.status === "open" || t.status === "overdue") && (
                  <>
                    <button className="b" onClick={() => act(t.id, "done")} disabled={busy}>
                      Gata
                    </button>
                    <button className="b" onClick={() => act(t.id, "skip")} disabled={busy}>
                      Omite
                    </button>
                  </>
                )}
                {canEdit && (t.status === "done" || t.status === "skipped") && (
                  <button className="b" onClick={() => act(t.id, "reopen")} disabled={busy}>
                    Redeschide
                  </button>
                )}
              </td>
            </tr>
          ))}
          {visible.length === 0 && (
            <tr>
              <td colSpan={4}>Nicio sarcină deschisă.</td>
            </tr>
          )}
        </tbody>
      </table>
      {canEdit && (
        <div className="bar">
          <input placeholder="Sarcină nouă" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Sarcină nouă" />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Termen" />
          <button className="b primary" onClick={add} disabled={busy || !title.trim() || !due}>
            Adaugă
          </button>
        </div>
      )}

      <h2>Șabloane recurente</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>Șablon</th>
            <th>Regulă</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {templates.map((t) => (
            <tr key={t.id}>
              <td>{t.title}</td>
              <td>{t.recurrence}</td>
              <td>
                {canTemplates && !t.standard && (
                  <button className="b" onClick={() => removeTemplate(t.id)} disabled={busy}>
                    Șterge
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {canTemplates && (
        <div className="bar">
          <input placeholder="Denumire" value={tplTitle} onChange={(e) => setTplTitle(e.target.value)} aria-label="Denumire șablon" />
          <input value={tplRule} onChange={(e) => setTplRule(e.target.value)} aria-label="Regulă" size={36} />
          <button className="b primary" onClick={addTemplate} disabled={busy || !tplTitle.trim()}>
            Adaugă șablon
          </button>
        </div>
      )}
      <div className="hint">Regulă: FREQ=MONTHLY;BYMONTHDAY=5 (lunar, ziua 5) sau FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=31 (anual).</div>
    </>
  );
}
