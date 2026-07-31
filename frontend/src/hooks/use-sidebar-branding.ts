import { useCallback, useEffect, useState } from "react";

export const SIDEBAR_BRANDING_STORAGE_KEY = "df-sidebar-branding-expanded";
export const SIDEBAR_BRANDING_CHANGE_EVENT = "df-sidebar-branding-change";

export function getSidebarBrandingExpanded(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(SIDEBAR_BRANDING_STORAGE_KEY) === "true";
}

export function setSidebarBrandingExpanded(expanded: boolean) {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(SIDEBAR_BRANDING_STORAGE_KEY, expanded ? "true" : "false");
  window.dispatchEvent(new CustomEvent(SIDEBAR_BRANDING_CHANGE_EVENT, { detail: expanded }));
}

export function useSidebarBrandingExpanded() {
  const [expanded, setExpanded] = useState(() => getSidebarBrandingExpanded());

  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<boolean>).detail;
      setExpanded(typeof detail === "boolean" ? detail : getSidebarBrandingExpanded());
    };
    window.addEventListener(SIDEBAR_BRANDING_CHANGE_EVENT, onChange);
    return () => window.removeEventListener(SIDEBAR_BRANDING_CHANGE_EVENT, onChange);
  }, []);

  const toggle = useCallback(() => {
    const next = !getSidebarBrandingExpanded();
    setSidebarBrandingExpanded(next);
    setExpanded(next);
  }, []);

  const set = useCallback((value: boolean) => {
    setSidebarBrandingExpanded(value);
    setExpanded(value);
  }, []);

  return { expanded, toggle, setExpanded: set };
}
