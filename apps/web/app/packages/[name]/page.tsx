import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  loadPackage,
  loadPackageMetadata,
  loadNearestScan,
  loadNearestRelease,
  hasOsvResult,
  failedField,
  badInput,
} from "../../../src/public-data";
import {
  Panel,
  Freshness,
  PypiSnapshot,
  ProjectionNote,
  RepositorySummary,
  Scan,
  date,
} from "../../../src/public-ui";
import { CompareToggle } from "../../../src/comparison";
import { PackagePersonal } from "../../../src/account";
import { catalogReturn, one, packageURL, validName, type Search } from "../../../src/url-state";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ name: string }>; searchParams: Promise<Search> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { name } = await params;
  if (!validName(name)) return { title: "Пакет не найден", robots: { index: false } };
  const { data } = await loadPackageMetadata(name);
  const item = data?.package;
  return {
    title: item?.source === "PYPI" ? item.name : "Пакет не найден",
    description: item?.source === "PYPI" ? item.summary.slice(0, 160) : undefined,
    alternates: { canonical: packageURL(name) },
  };
}
export default async function PackagePage({ params, searchParams }: Props) {
  const { name } = await params;
  if (!validName(name)) notFound();
  const query = await searchParams;
  const backToCatalog = catalogReturn(query.from);
  const detailURL = (values: Record<string, string | undefined> = {}) =>
    packageURL(name, {
      ...values,
      from: backToCatalog === "/#catalog" ? undefined : backToCatalog,
    });
  const version = one(query.version).slice(0, 200);
  const releaseAfter = one(query.releases).slice(0, 2048);
  const dependencyAfter = one(query.dependencies).slice(0, 2048);
  const { data, error } = await loadPackage(name, version, releaseAfter, dependencyAfter);
  if (!data?.package && error)
    return (
      <>
        <section className="catalog empty-state" role="alert">
          <h1>{badInput(error) ? "Некорректная версия или страница" : "Данные недоступны"}</h1>
          <Link href={detailURL()}>Открыть пакет заново →</Link>
          {backToCatalog !== "/#catalog" && <Link href={backToCatalog}>К результатам поиска</Link>}
        </section>
      </>
    );
  if (!data?.package || data.package.source !== "PYPI") notFound();
  const item = data.package;
  const nearby =
    version && !item.selected && !badInput(error) && !failedField(error, "selected")
      ? await loadNearestRelease(item.id, version)
      : null;
  const release = version
    ? (item.selected ?? nearby?.data?.package?.nearestPypiRelease)
    : item.latest?.nodes[0];
  const repositoryDown =
    failedField(error, "repositories") || failedField(error, "githubFreshness");
  const scanDown = failedField(error, "scan") || failedField(nearby?.error, "scan");
  const fallback =
    release && !hasOsvResult(release.scan) && !scanDown
      ? await loadNearestScan(item.id, release.version)
      : null;
  return (
    <>
      <div className="breadcrumbs">
        <Link href={backToCatalog}>
          {backToCatalog === "/#catalog" ? "Каталог" : "К результатам поиска"}
        </Link>
        <span aria-hidden="true">/</span>
        <span>{item.name}</span>
      </div>
      <section className="catalog package-heading" aria-labelledby="package-title">
        <div className="section-heading">
          <h1 id="package-title">{item.name}</h1>
          <CompareToggle name={item.name} />
        </div>
        <p>{item.summary || "Описание отсутствует"}</p>
        <PackagePersonal id={item.id} />
        <div className="facts">
          <div>
            <span>Python</span>
            <strong>{item.requiresPython || "Не указано"}</strong>
          </div>
          <div>
            <span>Лицензия</span>
            <strong>{item.license || "Не указана"}</strong>
          </div>
          <div>
            <span>GitHub</span>
            <strong>★ {item.starProjection.stars?.toLocaleString("ru-RU") ?? "—"}</strong>
          </div>
        </div>
        <div className="source-line">
          <PypiSnapshot
            version={release?.version}
            fetchedAt={release?.fetchedAt}
            freshness={item.pypiFreshness}
          />
          <a
            href={`https://pypi.org/project/${encodeURIComponent(name)}/`}
            target="_blank"
            rel="noreferrer"
          >
            PyPI ↗
          </a>
        </div>
      </section>
      <div className="detail-grid">
        <Panel title="Репозитории" id="repositories-title">
          {repositoryDown ? (
            <p className="notice" role="status">
              GitHub недоступен. Метаданные пакета доступны.
            </p>
          ) : (
            <>
              <Freshness label="GitHub" value={item.githubFreshness} />
              {item.repositories?.nodes.length ? (
                <ul className="repository-list">
                  {item.repositories.nodes.map((link, index) => (
                    <li key={link.repository?.id ?? index}>
                      <RepositorySummary link={link} packageSummary={item.summary} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">
                  {item.githubFreshness?.status === "SUCCESS"
                    ? "Подтверждённых ссылок нет."
                    : "Связи ещё не получены."}
                </p>
              )}
              {item.repositories?.pageInfo.hasNextPage && (
                <p className="muted">Показаны первые 5 репозиториев.</p>
              )}
            </>
          )}
          <ProjectionNote value={item.starProjection} />
        </Panel>
        <Panel title="Версии" id="versions-title">
          <p className="muted">Только загруженные версии</p>
          <div className="version-list">
            {item.versions.nodes.map((row) => (
              <Link
                className={row.id === release?.id ? "version-link selected" : "version-link"}
                aria-current={row.id === release?.id ? "true" : undefined}
                key={row.id}
                href={detailURL({ version: row.version })}
              >
                {row.version}
                {row.isPrerelease && <small> prerelease</small>}
                {row.yanked && <small> отозвана</small>}
              </Link>
            ))}
          </div>
          {!item.versions.nodes.length && <p className="muted">Версии не загружены.</p>}
          <div className="pagination">
            {releaseAfter && <Link href={detailURL({ version })}>В начало</Link>}
            {item.versions.pageInfo.hasNextPage && (
              <Link
                href={detailURL({
                  version,
                  releases: item.versions.pageInfo.endCursor ?? "",
                })}
              >
                Ещё версии →
              </Link>
            )}
          </div>
        </Panel>
      </div>
      {release ? (
        <>
          {nearby && (
            <p className="notice">
              Для версии {version} нет данных PyPI. Показана ближайшая загруженная версия{" "}
              {release.version}.
            </p>
          )}
          <div className="release-heading">
            <h2>Версия {release.version}</h2>
            <span className="muted">PyPI · {date(release.fetchedAt)}</span>
          </div>
          {release.yanked && <p className="notice">Версия отозвана издателем.</p>}
          <div className="detail-grid release-grid">
            <Panel title="Зависимости" id="dependencies-title">
              <p className="muted">Объявленные требования, включая extras и условия</p>
              <ul className="dependency-list">
                {release.dependencies.nodes.map((dep) => (
                  <li key={dep.id}>
                    <code>{dep.raw}</code>
                    <Link
                      href={`/?q=${encodeURIComponent(dep.name)}`}
                      aria-label={`Найти ${dep.name}`}
                    >
                      ↗
                    </Link>
                  </li>
                ))}
              </ul>
              {!release.dependencies.nodes.length && (
                <p className="muted">
                  {dependencyAfter ? "Конец списка." : "Зависимости не заявлены."}
                </p>
              )}
              <div className="pagination">
                {dependencyAfter && (
                  <Link href={detailURL({ version: release.version })}>В начало</Link>
                )}
                {release.dependencies.pageInfo.hasNextPage && (
                  <Link
                    className="button secondary"
                    href={detailURL({
                      version: release.version,
                      dependencies: release.dependencies.pageInfo.endCursor ?? "",
                    })}
                  >
                    Ещё зависимости →
                  </Link>
                )}
              </div>
            </Panel>
            <Panel title="Уязвимости OSV" id="osv-title">
              <Scan
                scan={fallback?.scan ?? release.scan}
                selected={release.version}
                nearby={Boolean(fallback?.scan)}
                failed={release.scan?.status === "FAILED"}
                unavailable={scanDown || fallback?.unavailable}
              />
            </Panel>
          </div>
        </>
      ) : (
        <section className="catalog empty-state">
          <h2>
            {nearby?.error
              ? "Данные PyPI недоступны"
              : version
                ? "Версия не найдена в каталоге"
                : "Версии пока не загружены"}
          </h2>
          {version && <Link href={detailURL()}>Последняя загруженная версия →</Link>}
        </section>
      )}
    </>
  );
}
