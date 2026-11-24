import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useShell } from "../shell/tabs";

interface Message {
  id: number;
  role: string;
  content: string | null;
  tool_calls: { name: string }[] | null;
}

/** Chatul asistentului AI: răspunde din datele organizației; nu aplică nimic singur. */
export function AssistantScreen() {
  const { orgId } = useShell();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const base = `/organizations/${orgId}/assistant`;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  async function send() {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setError(null);
    try {
      let id = conversationId;
      if (!id) {
        id = (await api<{ id: string }>(`${base}/conversations`, { method: "POST", body: {} })).id;
        setConversationId(id);
      }
      setMessages((m) => [...m, { id: -Date.now(), role: "user", content, tool_calls: null }]);
      setText("");
      const answer = await api<Message>(`${base}/conversations/${id}/messages`, {
        method: "POST",
        body: { content, context: { screen: "assistant" } },
      });
      setMessages((m) => [...m, answer]);
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id >= 0));
      setText(content);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Asistent AI</h1>
      <p className="muted">Răspunde din datele organizației, cu drepturile dumneavoastră. Sugestiile de înregistrări nu se aplică singure.</p>
      <div style={{ minHeight: 240, maxHeight: "55vh", overflowY: "auto", border: "1px solid #ccc", padding: 8 }}>
        {messages.length === 0 && <p className="muted">Întrebați, de ex.: „Ce înseamnă Dt 242 / Kt 521?” sau „Care este soldul contului 521?”.</p>}
        {messages.map((m) => (
          <p key={m.id} style={{ whiteSpace: "pre-wrap", fontWeight: m.role === "user" ? 600 : 400 }}>
            {m.role === "user" ? "Dvs.: " : "Asistent: "}
            {m.content}
            {m.tool_calls && <span className="muted"> (consultat: {m.tool_calls.map((t) => t.name).join(", ")})</span>}
          </p>
        ))}
        <div ref={end} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="bar">
        <input
          className="b"
          style={{ flex: 1 }}
          aria-label="Mesaj"
          value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="b primary" disabled={busy || !text.trim()} onClick={send}>
          {busy ? "Se gândește…" : "Trimite"}
        </button>
      </div>
    </>
  );
}
