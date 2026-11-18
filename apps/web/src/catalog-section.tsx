"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

export function CatalogSection({ children }: { children: ReactNode }) {
  const section = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    // The fragment can arrive before Next streams the catalog into the page.
    if (window.location.hash === "#catalog")
      section.current?.scrollIntoView({ behavior: "instant" });
  }, []);
  return (
    <section
      ref={section}
      className="catalog catalog-index"
      id="catalog"
      aria-labelledby="catalog-title"
    >
      {children}
    </section>
  );
}
