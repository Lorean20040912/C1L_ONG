import type { Section } from "./sections";
import { useProfile } from "./profile";
import { SCREEN_LINKS, newId, useShell } from "./tabs";

export function SectionPanel({ section }: { section: Section }) {
  const { openTab } = useShell();
  const profile = useProfile();
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
              {links.filter((title) => profile.screenVisible(title)).map((title) => {
                const kind = SCREEN_LINKS[title];
                return (
                  <li key={title}>
                    <button
                      className="link"
                      onClick={() =>
                        openTab(kind === "manual" ? { id: newId("manual"), title, kind } : kind ? { id: kind, title, kind } : { id: `screen:${section.id}:${title}`, title, kind: "placeholder" })
                      }
                    >
                      {title}
                    </button>
                    {!kind && <span className="muted"> · în lucru</span>}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}
