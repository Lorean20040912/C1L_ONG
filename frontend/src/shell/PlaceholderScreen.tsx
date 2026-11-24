export function PlaceholderScreen({ title }: { title: string }) {
  return (
    <>
      <h1>{title}</h1>
      <div className="hint">Ecranul nu este încă implementat — vine odată cu modulul său.</div>
    </>
  );
}
