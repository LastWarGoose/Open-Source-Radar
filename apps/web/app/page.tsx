import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { getClient } from "../src/apollo-server";
import { PublicCatalogDocument } from "../src/gql/graphql";
import { PackageActions, PackageActionsProvider } from "../src/package-actions";
import { CatalogFilters } from "../src/catalog-filters";
import { CatalogSection } from "../src/catalog-section";
import { badInput, loadCatalogLicenses } from "../src/public-data";
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
  const result = queryCatalog(state);
  return (
    <>
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
      <CatalogSection resultsURL={resultsURL}>
        <div className="section-heading">
          <h2 id="catalog-title">Пакеты</h2>
          <span className="count">PyPI</span>
        </div>
        <CatalogFilters key={resultsURL} state={state}>
          <Suspense
            fallback={<LicenseSelect selected={state.license} placeholder="Загрузка лицензий…" />}
          >
            <LicenseOptions selected={state.license} result={result} />
          </Suspense>
        </CatalogFilters>
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
        <Suspense key={`results:${resultsURL}`} fallback={<p role="status">Загрузка пакетов…</p>}>
          <CatalogResults state={state} resultsURL={resultsURL} result={result} />
        </Suspense>
      </CatalogSection>
    </>
  );
}

type CatalogState = ReturnType<typeof catalogState>;

function queryCatalog(state: CatalogState) {
  return getClient().query({
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
}

type CatalogResult = ReturnType<typeof queryCatalog>;

function LicenseSelect({
  selected,
  options = [],
  placeholder = "Все лицензии",
}: {
  selected: string;
  options?: string[];
  placeholder?: string;
}) {
  return (
    <select name="license" defaultValue={selected}>
      <option value="">{placeholder}</option>
      {selected && !options.includes(selected) && <option>{selected}</option>}
      {options.map((license) => (
        <option key={license}>{license}</option>
      ))}
    </select>
  );
}

async function LicenseOptions({ selected, result }: { selected: string; result: CatalogResult }) {
  const { data } = await result;
  const options = data ? await loadCatalogLicenses(data.catalogLicenseRevision) : null;
  return options ? (
    <LicenseSelect selected={selected} options={options} />
  ) : (
    <LicenseSelect selected={selected} placeholder="Список лицензий недоступен" />
  );
}

async function CatalogResults({
  state,
  resultsURL,
  result,
}: {
  state: CatalogState;
  resultsURL: string;
  result: CatalogResult;
}) {
  const { data, error } = await result;
  return !data?.packages ? (
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
      <PackageActionsProvider ids={data.packages.nodes.map((item) => item.id)}>
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
                {item.summary && <p className="package-summary">{item.summary}</p>}
                {(item.license || item.requiresPython) && (
                  <div className="package-meta">
                    {item.license && <span>{item.license}</span>}
                    {item.requiresPython && <span>Python {item.requiresPython}</span>}
                  </div>
                )}
                {item.pypiFreshness.errorCode && (
                  <small className="attention">Не удалось обновить данные PyPI</small>
                )}
              </div>
              <div className="package-actions">
                <span
                  className="star-count"
                  title={
                    item.starProjection.stars == null
                      ? "Число звёзд GitHub неизвестно"
                      : "Звёзды GitHub"
                  }
                >
                  ★ {item.starProjection.stars?.toLocaleString("ru-RU") ?? "—"}
                </span>
                <PackageActions name={item.name} id={item.id} />
                {item.starProjection.status === "FAILED" && (
                  <small className="attention">Не удалось обновить звёзды GitHub</small>
                )}
              </div>
            </article>
          ))}
        </div>
      </PackageActionsProvider>
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
  );
}
