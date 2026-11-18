import type { Metadata } from "next";
import { AdminPage } from "../../src/admin";

export const metadata: Metadata = { title: "Импорт", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default function Page() {
  return <AdminPage />;
}
