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
    const { hash, search } = window.location;
    // A shared query without a fragment can render before hydration. Respect an
    // existing scroll position if the reader has already moved to a result.
    if (hash === "#radar") window.scrollTo({ top: 0, behavior: "instant" });
    else if (hash === "#catalog" || (!hash && search && window.scrollY === 0))
      section.current?.scrollIntoView({ behavior: "instant" });
  }, [resultsURL]);
  return (
    <section
      ref={section}
      className="catalog catalog-index"
      id="catalog"
      tabIndex={-1}
      aria-labelledby="catalog-title"
    >
      {children}
    </section>
  );
}
