export function Messages({ error, info }: { error: string | null; info: string | null }) {
  return (
    <>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {info && (
        <div className="hint" role="status">
          {info}
        </div>
      )}
    </>
  );
}

export function ReadOnlyNote({ show, what }: { show: boolean; what: string }) {
  return show ? <div className="hint">Rolul dumneavoastră permite doar vizualizarea; {what}.</div> : null;
}
