import type { Metadata } from "next";
import Link from "next/link";
import { getClient } from "../../src/apollo-server";
import { ComparePackagesDocument } from "../../src/gql/graphql";
import { date, Freshness, ProjectionNote, RepositorySummary } from "../../src/public-ui";
import { compareURL, one, validName, packageURL, type Search } from "../../src/url-state";
import { RemoveComparison } from "../../src/comparison";
import { failedField } from "../../src/public-data";

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
          <a href={compareURL(names)}>Повторить сравнение →</a>
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
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Таблица сравнения">
          <table className="comparison-table">
            <thead>
              <tr>
                <th scope="col">Параметр</th>
                {names.map((name, index) => (
                  <th scope="col" key={name}>
                    <Link href={packageURL(name)}>{name}</Link>
                    <RemoveComparison name={name} remaining={names.filter((_, i) => i !== index)} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Описание пакета</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source === "PYPI" ? item.summary || "Нет описания" : "—"}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">Версия в каталоге</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source === "PYPI"
                      ? (item.current.nodes[0]?.version ?? "Не загружена")
                      : "Пакет не найден"}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">Python</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source === "PYPI" ? item.requiresPython || "Не указано" : "—"}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">Лицензия</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source === "PYPI" ? item.license || "Не указана" : "—"}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">Звёзды GitHub</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source === "PYPI"
                      ? (item.starProjection.stars?.toLocaleString("ru-RU") ?? "Не получены")
                      : "—"}
                    {item?.source === "PYPI" && (
                      <small>
                        <ProjectionNote value={item.starProjection} />
                      </small>
                    )}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">Репозитории</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source !== "PYPI" ? (
                      "—"
                    ) : item.repositories?.nodes.length ? (
                      <>
                        {item.repositories.nodes.map((link, n) => (
                          <RepositorySummary key={link.repository?.id ?? n} link={link} />
                        ))}
                        {item.repositories.pageInfo.hasNextPage && (
                          <small>Показаны первые 5 репозиториев.</small>
                        )}
                      </>
                    ) : item.githubFreshness?.status === "SUCCESS" ? (
                      "Нет подтверждённых"
                    ) : (
                      "Нет данных"
                    )}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">OSV · выбранная версия</th>
                {items.map((item, i) => {
                  const scan = item?.source === "PYPI" ? item.current.nodes[0]?.scan : null;
                  return (
                    <td key={names[i]}>
                      {scan?.status === "SUCCESS"
                        ? scan.findings.nodes.length
                          ? `Найдено: ${scan.findings.nodes.length}${scan.findings.pageInfo.hasNextPage ? "+" : ""}`
                          : "Совпадений нет"
                        : scan?.status === "STALE"
                          ? "Результат устарел"
                          : scan?.status === "FAILED"
                            ? "Ошибка проверки"
                            : !scan && failedField(result.error, "scan")
                              ? "Недоступно"
                              : "Не проверено"}
                      {scan?.lastSuccessAt && (
                        <small className="muted">{date(scan.lastSuccessAt)}</small>
                      )}
                    </td>
                  );
                })}
              </tr>
              <tr>
                <th scope="row">Обновление PyPI</th>
                {items.map((item, i) => (
                  <td key={names[i]}>
                    {item?.source === "PYPI" ? <Freshness value={item.pypiFreshness} /> : "—"}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="muted comparison-note">
          Звёзды — максимум среди подтверждённых репозиториев. Отсутствие совпадений OSV не
          гарантирует безопасность.
        </p>
      </section>
    </>
  );
}
