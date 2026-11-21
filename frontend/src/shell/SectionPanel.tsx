import type { Section } from "./sections";

export function SectionPanel({ section, onOpen }: { section: Section; onOpen: (id: string, title: string) => void }) {
  const groups = Object.entries(section.groups ?? {});
  return (
    <>
      <h1>{section.title}</h1>
      {groups.length === 0 && <p className="muted">Secțiunea se completează odată cu modulele ei.</p>}
      <div className="navgroups">
        {groups.map(([group, links]) => (
          <div key={group}>
            <h3>{group}</h3>
            <ul>
              {links.map((title) => (
                <li key={title}>
                  <button className="link" onClick={() => onOpen(`screen:${section.id}:${title}`, title)}>
                    {title}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}
