import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../api/client";

/** Profilul organizației (docs/13): ce secțiuni și ecrane sunt pornite de funcționalitățile ei. */
export interface UiProfile {
  enabled: string[];
  gated_sections: string[];
  visible_sections: string[];
  gated_screens: string[];
  visible_screens: string[];
}

export interface ProfileApi {
  /** secțiunea apare dacă nu e legată de nicio funcționalitate sau una dintre ele e pornită */
  sectionVisible: (id: string) => boolean;
  screenVisible: (title: string) => boolean;
  refresh: () => void;
}

const SHOW_ALL: ProfileApi = { sectionVisible: () => true, screenVisible: () => true, refresh: () => {} };

export const ProfileContext = createContext<ProfileApi>(SHOW_ALL);

export const useProfile = () => useContext(ProfileContext);

/** Încarcă profilul; până se încarcă (sau la eroare) nu se ascunde nimic. */
export function useProfileLoader(orgId: string): ProfileApi {
  const [profile, setProfile] = useState<UiProfile | null>(null);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let current = true;
    setProfile(null);
    if (orgId)
      api<UiProfile>(`/organizations/${orgId}/ui-profile`)
        .then((p) => current && setProfile(p))
        .catch(() => current && setProfile(null));
    return () => {
      current = false;
    };
  }, [orgId, version]);

  if (!profile) return { ...SHOW_ALL, refresh };
  return {
    sectionVisible: (id) => !profile.gated_sections.includes(id) || profile.visible_sections.includes(id),
    screenVisible: (t) => !profile.gated_screens.includes(t) || profile.visible_screens.includes(t),
    refresh,
  };
}
