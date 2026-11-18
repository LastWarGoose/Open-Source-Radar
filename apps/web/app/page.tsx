import type { Metadata } from "next";
import Form from "next/form";
import Link from "next/link";
import { getClient } from "../src/apollo-server";
import { PublicCatalogDocument } from "../src/gql/graphql";
import { CompareToggle } from "../src/comparison";
import { CatalogSection } from "../src/catalog-section";
import { Freshness, ProjectionNote } from "../src/public-ui";
import { badInput } from "../src/public-data";
import { catalogState, catalogURL, packageURL, type Search } from "../src/url-state";

export const dynamic = "force-dynamic";
export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<Search>;
}): Promise<Metadata> {
  const state = catalogState(await searchParams);
  return {
    title: "Каталог Python-библиотек",
    alternates: { canonical: "/" },
    ...(state.q || state.after || state.license || state.releases
      ? { robots: { index: false, follow: true } }
      : {}),
  };
}
export default async function Page({ searchParams }: { searchParams: Promise<Search> }) {
  const params = await searchParams;
  const state = catalogState(params);
  const resultsURL = catalogURL(state, state.after, state.trail);
  const clearFiltersURL = catalogURL({ ...state, q: "", license: "", releases: "" });
  const activeFilters = [
    { key: "q", label: `Поиск · ${state.q}`, value: state.q },
    { key: "license", label: `Лицензия · ${state.license}`, value: state.license },
    {
      key: "releases",
      label: state.releases === "yes" ? "Есть версии" : "Без версий",
      value: state.releases,
    },
  ].filter((filter) => filter.value);
  const landing = !["q", "license", "releases", "sort", "after", "back", "size"].some(
    (key) => params[key] !== undefined,
  );
  const { data, error } = await getClient().query({
    query: PublicCatalogDocument,
    variables: {
      first: state.size,
      after: state.after || null,
      search: state.q || null,
      sort: state.sort,
      filter: {
        source: "PYPI",
        license: state.license || null,
        hasReleases: state.releases ? state.releases === "yes" : null,
      },
    },
    errorPolicy: "all",
  });
  return (
    <>
      {landing && (
        <section className="catalog-intro" aria-labelledby="intro-title">
          <div className="intro-sectors" aria-hidden="true">
            {Array.from({ length: 8 }, (_, column) => (
              <span key={column} />
            ))}
          </div>
          <p className="intro-sources">
            <span>Источники</span>
            PyPI, GitHub, OSV
          </p>
          <h1 id="intro-title">
            Каталог библиотек <span>Python</span>
          </h1>
          <a className="intro-jump" href="#catalog">
            Перейти к поиску <span aria-hidden="true">↓</span>
          </a>
        </section>
      )}
      <CatalogSection key={landing ? "landing" : "results"}>
        <div className="section-heading">
          {landing ? <h2 id="catalog-title">Пакеты</h2> : <h1 id="catalog-title">Каталог</h1>}
          <span className="count">PyPI</span>
        </div>
        <Form className="filters" action="/" key={catalogURL(state)} role="search">
          <label className="search-field">
            Поиск
            <input
              name="q"
              type="search"
              defaultValue={state.q}
              maxLength={200}
              placeholder="Название или описание"
            />
          </label>
          <label>
            Лицензия
            <input
              name="license"
              defaultValue={state.license}
              maxLength={200}
              placeholder="Например, MIT"
            />
          </label>
          <label htmlFor="release-filter">
            Версии
            <select id="release-filter" name="releases" defaultValue={state.releases}>
              <option value="">Все</option>
              <option value="yes">Есть в каталоге</option>
              <option value="no">Не загружены</option>
            </select>
          </label>
          <label htmlFor="sort-filter">
            Сортировка
            <select id="sort-filter" name="sort" defaultValue={state.sort}>
              <option value="RELEVANCE">Релевантность</option>
              <option value="NAME_ASC">Название</option>
              <option value="UPDATED_DESC">Обновление</option>
              <option value="STARS_DESC">Звёзды GitHub</option>
            </select>
          </label>
          <input type="hidden" name="size" value={state.size} />
          <button type="submit">Найти</button>
        </Form>
        {activeFilters.length > 0 && (
          <nav className="filter-summary" aria-label="Активные фильтры">
            {activeFilters.map(({ key, label }) => (
              <Link
                className="button secondary"
                key={key}
                href={catalogURL({ ...state, [key]: "" })}
                aria-label={`Убрать фильтр «${label}»`}
              >
                {label} <span aria-hidden="true">×</span>
              </Link>
            ))}
            {activeFilters.length > 1 && <Link href={clearFiltersURL}>Сбросить все</Link>}
          </nav>
        )}
        {!data?.packages ? (
          <div className="empty-state" role="alert">
            <h2>{badInput(error) ? "Страница устарела" : "Каталог недоступен"}</h2>
            <Link href={catalogURL(state)}>Открыть каталог заново →</Link>
          </div>
        ) : !data.packages.nodes.length ? (
          <div className="empty-state">
            <h2>Пакеты не найдены</h2>
          </div>
        ) : (
          <>
            <div className="public-package-list">
              {data.packages.nodes.map((item) => (
                <article className="public-package-row" key={item.id} data-testid="catalog-package">
                  <div className="package-main">
                    <div className="package-name">
                      <h2>
                        <Link
                          href={packageURL(item.name, {
                            from: resultsURL === "/#catalog" ? undefined : resultsURL,
                          })}
                        >
                          {item.name}
                        </Link>
                      </h2>
                      <span className="version-tag">
                        {item.releases.nodes[0]?.version ?? "Нет версий"}
                      </span>
                    </div>
                    <p className="package-summary">{item.summary || "Описание отсутствует"}</p>
                    <div className="package-meta">
                      <span>{item.license || "Лицензия не указана"}</span>
                      <span>Python {item.requiresPython || "—"}</span>
                    </div>
                    <Freshness value={item.pypiFreshness} label="PyPI" />
                  </div>
                  <div className="package-actions">
                    <span className="star-count">
                      ★ {item.starProjection.stars?.toLocaleString("ru-RU") ?? "—"}
                    </span>
                    <CompareToggle name={item.name} />
                    <ProjectionNote value={item.starProjection} />
                  </div>
                </article>
              ))}
            </div>
            <nav className="pagination" aria-label="Страницы каталога">
              <span className="muted">На странице: {data.packages.nodes.length}</span>
              {state.after && (
                <>
                  <Link className="button secondary" href={catalogURL(state)}>
                    В начало
                  </Link>
                  <Link
                    className="button secondary"
                    href={catalogURL(state, state.trail.at(-1) ?? "", state.trail.slice(0, -1))}
                  >
                    ← Назад
                  </Link>
                </>
              )}
              {data.packages.pageInfo.hasNextPage && (
                <Link
                  className="button"
                  href={catalogURL(state, data.packages.pageInfo.endCursor ?? "", [
                    ...state.trail,
                    state.after,
                  ])}
                >
                  Далее →
                </Link>
              )}
            </nav>
          </>
        )}
      </CatalogSection>
    </>
  );
}
