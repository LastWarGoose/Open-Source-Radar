"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

export function CatalogSection({
  children,
  resultsURL,
}: {
  children: ReactNode;
  resultsURL: string;
}) {
  const section = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    // The fragment can arrive before Next streams the catalog into the page.
    if (window.location.hash === "#catalog" || (!window.location.hash && window.location.search))
      section.current?.scrollIntoView({ behavior: "instant" });
  }, [resultsURL]);
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
