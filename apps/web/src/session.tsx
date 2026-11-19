"use client";

import { useQuery } from "@apollo/client/react";
import { createContext, useContext, type ReactNode } from "react";
import { SessionDocument } from "./gql/graphql";

function useSessionQuery() {
  return useQuery(SessionDocument, {
    ssr: false,
    fetchPolicy: "network-only",
    pollInterval: 15000,
  });
}
const SessionContext = createContext<ReturnType<typeof useSessionQuery> | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const session = useSessionQuery();
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is missing");
  return session;
}
