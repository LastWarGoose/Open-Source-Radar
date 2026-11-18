import Link from "next/link";
import { CompareDock, CompareNav } from "./comparison";
import { AccountNav } from "./account";
import type {
  FreshnessFieldsFragment,
  ScanFieldsFragment,
  CatalogItemFragment,
  RepositoryDetailsFragment,
} from "./gql/graphql";

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="site">
      <a href="#content" className="skip-link">
        К содержимому
      </a>
      <div className="masthead" aria-hidden="true">
        <span className="masthead-word">
          {["R", "A", "D", "A", "R"].map((letter, index) => (
            <span key={index}>{letter}</span>
          ))}
        </span>
      </div>
      <header className="site-header">
        <nav aria-label="Основная навигация">
          <Link href="/" className="brand" aria-label="Open Source Radar — на главную">
            <span className="registration-mark" aria-hidden="true" />
            <span>Open Source Radar</span>
          </Link>
          <Link href="/#catalog">Каталог</Link>
          <CompareNav />
          <AccountNav />
        </nav>
      </header>
      <main id="content" tabIndex={-1}>
        {children}
      </main>
      <CompareDock />
    </div>
  );
}
export function Panel({
  title,
  children,
  id,
}: {
  title: string;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <section className="catalog panel" aria-labelledby={id ?? undefined}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}
export function date(value: string | null | undefined) {
  if (!value) return "—";
  return (
    new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(new Date(value)) + " UTC"
  );
}
export function RepositorySummary({
  link,
  packageSummary,
}: {
  link: RepositoryDetailsFragment;
  packageSummary?: string;
}) {
  const repo = link.repository;
  if (!repo) return <span className="muted">Репозиторий недоступен</span>;
  return (
    <div className="repo-summary">
      <a className="repo-link" href={repo.url} target="_blank" rel="noreferrer">
        {repo.fullName} <span aria-hidden="true">↗</span>
      </a>
      {repo.description ? (
        <p>{repo.description}</p>
      ) : packageSummary ? (
        <p>
          <small className="summary-source">О пакете · PyPI</small>
          {packageSummary}
        </p>
      ) : (
        <p className="muted">Описание GitHub пока недоступно.</p>
      )}
      <small className="muted">
        ★ {repo.stars.toLocaleString("ru-RU")}
        {link.status !== "VERIFIED" && " · Связь не подтверждена"}
      </small>
    </div>
  );
}
export function Freshness({
  value,
  label,
}: {
  value?: FreshnessFieldsFragment | null;
  label?: string;
}) {
  const labels: Record<string, string> = {
    UNKNOWN: "Не проверено",
    SUCCESS: "Обновлено",
    STALE: "Устарело",
    FAILED: "Ошибка проверки",
  };
  return (
    <span className={`freshness ${value?.status === "SUCCESS" ? "" : "attention"}`}>
      <span>
        {label && label + ": "}
        {value ? (labels[value.status] ?? "Не проверено") : "Недоступен"}
      </span>
      {value?.lastSuccessAt && (
        <time dateTime={value.lastSuccessAt} title="Последняя успешная проверка">
          {date(value.lastSuccessAt)}
        </time>
      )}
    </span>
  );
}
export function ProjectionNote({
  value,
}: {
  value: Pick<
    CatalogItemFragment["starProjection"],
    "status" | "checkedAt" | "projectedAt" | "lagSeconds"
  >;
}) {
  if (!value.checkedAt) return <span className="muted">Звёзды ещё не получены</span>;
  return (
    <span
      className="muted"
      title={`GitHub: ${date(value.checkedAt)}. Каталог: ${date(value.projectedAt)}`}
    >
      GitHub · {date(value.checkedAt)}
      {value.lagSeconds != null && ` · задержка ${value.lagSeconds}\u00a0с`}
      {value.status !== "SUCCESS" ? " · данные устарели" : ""}
    </span>
  );
}
export function Scan({
  scan,
  unavailable = false,
}: {
  scan?: ScanFieldsFragment | null;
  unavailable?: boolean;
}) {
  if (unavailable)
    return (
      <p role="status" className="notice">
        OSV недоступен. Повторите позже.
      </p>
    );
  if (!scan || scan.status === "UNKNOWN")
    return <p className="muted">Эта версия ещё не проверена.</p>;
  return (
    <>
      <Freshness
        label="OSV"
        value={{
          status: scan.status,
          checkedAt: scan.checkedAt,
          lastSuccessAt: scan.lastSuccessAt,
          errorCode: scan.errorCode,
        }}
      />
      {scan.status !== "SUCCESS" && (
        <p className="notice">
          {scan.lastSuccessAt
            ? "Показан последний сохранённый результат."
            : "Проверка не завершена."}
        </p>
      )}
      {scan.findings.nodes.length > 0 ? (
        <ul className="findings">
          {scan.findings.nodes.map((item) => (
            <li key={item.id}>
              <a
                href={`https://osv.dev/vulnerability/${encodeURIComponent(item.id)}`}
                target="_blank"
                rel="noreferrer"
              >
                {item.id} ↗
              </a>
              <p>{item.summary}</p>
              <small className="muted">
                {item.aliases.nodes
                  .filter((alias) => alias.name !== item.id)
                  .map((alias) => alias.name)
                  .join(" · ")}
              </small>
            </li>
          ))}
        </ul>
      ) : (
        scan.status === "SUCCESS" && <p>Совпадений не найдено. Это не гарантия безопасности.</p>
      )}
      {scan.findings.pageInfo.hasNextPage && (
        <p className="notice">Показаны первые 100 записей OSV.</p>
      )}
    </>
  );
}
