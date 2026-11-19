"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export function HomeAnchor({
  id,
  children,
  ...props
}: {
  id: "radar" | "catalog";
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
}) {
  const pathname = usePathname();
  if (pathname === "/")
    return (
      <a
        href={`#${id}`}
        {...props}
        onClick={(event) => {
          if (
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey ||
            event.button !== 0
          )
            return;
          const target = document.getElementById(id);
          if (!target) return;
          event.preventDefault();
          const hash = `#${id}`;
          if (location.hash !== hash) window.history.pushState(null, "", hash);
          const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth";
          if (id === "radar") {
            // Let the sticky header finish moving if this click interrupts a catalog scroll.
            requestAnimationFrame(() => {
              if (location.hash === hash) window.scrollTo({ top: 0, behavior });
            });
          } else {
            target.focus({ preventScroll: true });
            target.scrollIntoView({ block: "start", behavior });
          }
        }}
      >
        {children}
      </a>
    );
  return (
    <Link href={`/#${id}`} {...props}>
      {children}
    </Link>
  );
}
