import type { Metadata } from "next";
import Link from "next/link";
import { getClient } from "../../src/apollo-server";
import { ComparePackagesDocument } from "../../src/gql/graphql";
import { compareURL, one, validName, type Search } from "../../src/url-state";
import { ComparisonTable } from "../../src/comparison";
import { comparisonRows } from "./rows";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Сравнение пакетов",
  robots: { index: false, follow: true },
  alternates: { canonical: "/compare" },
};
export default async function ComparePage({ searchParams }: { searchParams: Promise<Search> }) {
  const query = await searchParams;
  const names = [...new Set(one(query.packages).split(",").filter(Boolean))];
  if (names.length > 4 || names.some((name) => !validName(name)))
    return (
      <>
        <section className="catalog empty-state" role="alert">
          <h1>Можно сравнить до 4 пакетов</h1>
          <Link href="/#catalog">Выбрать в каталоге →</Link>
        </section>
      </>
    );
  if (!names.length)
    return (
      <>
        <section className="catalog empty-state">
          <h1>Сравнение</h1>
          <p className="muted">Выберите до 4 пакетов в каталоге.</p>
          <Link className="button" href="/#catalog">
            Открыть каталог →
          </Link>
        </section>
      </>
    );
  const result = await getClient().query({
    query: ComparePackagesDocument,
    variables: {
      a: "pypi:" + names[0],
      b: "pypi:" + (names[1] ?? ""),
      c: "pypi:" + (names[2] ?? ""),
      d: "pypi:" + (names[3] ?? ""),
      hasB: names.length > 1,
      hasC: names.length > 2,
      hasD: names.length > 3,
    },
    errorPolicy: "all",
  });
  const items = [result.data?.a, result.data?.b, result.data?.c, result.data?.d].slice(
    0,
    names.length,
  );
  if (result.error && items.every((item) => !item))
    return (
      <>
        <section className="catalog empty-state" role="alert">
          <h1>Сравнение недоступно</h1>
          <a href={compareURL(names, one(query.differences) === "1")}>Повторить сравнение →</a>
        </section>
      </>
    );
  return (
    <>
      <section className="catalog">
        <div className="section-heading">
          <h1>Сравнение</h1>
          <Link href="/#catalog">← Каталог</Link>
        </div>
        {result.error && (
          <p className="notice" role="status">
            Часть данных недоступна. Показаны доступные сведения.
          </p>
        )}
        <ComparisonTable names={names} rows={await comparisonRows(items, result.error)} />
        <p className="muted comparison-note">
          Звёзды — максимум среди подтверждённых репозиториев. Отсутствие совпадений OSV не
          гарантирует безопасность.
        </p>
      </section>
    </>
  );
}
