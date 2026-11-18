import type { Metadata } from "next";
import { AccountPage } from "../../src/account";
import { one, type Search } from "../../src/url-state";

export const metadata: Metadata = {
  title: "Личный кабинет",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";
export default async function Page({ searchParams }: { searchParams: Promise<Search> }) {
  return <AccountPage section={one((await searchParams).section)} />;
}
