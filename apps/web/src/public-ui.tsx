import { CompareNav } from "./comparison";
import { HomeAnchor } from "./site-navigation";
import { AccountNav } from "./account";
import type {
  FreshnessFieldsFragment,
  ScanFieldsFragment,
  ScanSummaryFragment,
  OverviewFragment,
  RepositoryDetailsFragment,
} from "./gql/graphql";

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="site">
      <a href="#content" className="skip-link">
        К содержимому
      </a>
      <div id="radar" className="masthead" aria-hidden="true">
        <span className="masthead-word">
          {["R", "A", "D", "A", "R"].map((letter, index) => (
            <span key={index}>
              <span className="masthead-letter">{letter}</span>
            </span>
          ))}
        </span>
      </div>
      <header className="site-header">
        <nav aria-label="Основная навигация">
          <HomeAnchor id="radar" className="brand" aria-label="Open Source Radar — на главную">
            <span className="registration-mark" aria-hidden="true" />
            <span>Open Source Radar</span>
          </HomeAnchor>
          <HomeAnchor id="catalog">Каталог</HomeAnchor>
          <CompareNav />
          <AccountNav />
        </nav>
      </header>
      <main id="content" tabIndex={-1}>
        {children}
      </main>
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
    OverviewFragment["starProjection"],
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
type SavedScan = ScanFieldsFragment | ScanSummaryFragment;

export function PypiSnapshot({
  version,
  fetchedAt,
  freshness,
}: {
  version?: string;
  fetchedAt?: string;
  freshness: FreshnessFieldsFragment;
}) {
  const stamp = fetchedAt ?? freshness.lastSuccessAt;
  return (
    <span className="freshness">
      <span>{version ? `PyPI · ${version}` : "PyPI · нет загруженной версии"}</span>
      {stamp && <time dateTime={stamp}>Данные от {date(stamp)}</time>}
      {freshness.errorCode && <small className="attention">Последнее обновление не удалось</small>}
    </span>
  );
}

export function Scan({
  scan,
  selected,
  nearby = false,
  unavailable = false,
  compact = false,
  failed = false,
}: {
  scan?: SavedScan | null;
  selected: string;
  nearby?: boolean;
  unavailable?: boolean;
  compact?: boolean;
  failed?: boolean;
}) {
  if (unavailable)
    return (
      <span className="notice" role="status">
        OSV недоступен. Повторите позже.
      </span>
    );
  if (!scan?.lastSuccessAt || scan.source !== "OSV")
    return (
      <span className="muted">
        {failed || scan?.status === "FAILED"
          ? "Проверка не завершена."
          : "Эта версия ещё не проверена."}
      </span>
    );
  const checkedVersion = scan.version ?? selected;
  const hits = scan.findings.nodes;
  const fixes = new Map(scan.fixes.nodes.map((fix) => [fix.advisoryId, fix.version]));
  const historical = scan.fixes.nodes.filter((fix) => fix.historical);
  const entries = (
    <ul className="findings">
      {hits.map((item) => (
        <li key={item.id}>
          <a
            href={`https://osv.dev/vulnerability/${encodeURIComponent(item.id)}`}
            target="_blank"
            rel="noreferrer"
          >
            {item.id}
            <span aria-hidden="true"> ↗</span>
          </a>
          {fixes.has(item.id) && (
            <strong className="fix-version">Исправлено в {fixes.get(item.id)}</strong>
          )}
          {!compact && "summary" in item && <p>{item.summary}</p>}
          {!compact && "aliases" in item && (
            <small className="muted">
              {item.aliases.nodes
                .filter((alias) => alias.name !== item.id)
                .map((alias) => alias.name)
                .join(" · ")}
            </small>
          )}
        </li>
      ))}
    </ul>
  );
  return (
    <div className="scan-result">
      {nearby && (
        <small className="notice">
          {failed
            ? `Проверка версии ${selected} не завершена.`
            : `Для версии ${selected} нет проверки.`}{" "}
          Ближайшая проверенная — {checkedVersion}.
        </small>
      )}
      {hits.length ? (
        compact ? (
          <details open={hits.length <= 3}>
            <summary>
              Найдено: {hits.length}
              {scan.findings.pageInfo.hasNextPage ? "+" : ""}
            </summary>
            {entries}
          </details>
        ) : (
          entries
        )
      ) : (
        <span>Совпадений не найдено.</span>
      )}
      {historical.map((fix) => (
        <small key={fix.advisoryId} className="fix-version">
          <a
            href={`https://osv.dev/vulnerability/${encodeURIComponent(fix.advisoryId)}`}
            target="_blank"
            rel="noreferrer"
          >
            {fix.advisoryId}
          </a>{" "}
          · Исправлено в {fix.version}
        </small>
      ))}
      {scan.fixes.pageInfo.hasNextPage && <small>Показаны первые 100 исправлений.</small>}
      <small className="muted">
        OSV · {checkedVersion} ·{" "}
        <time dateTime={scan.lastSuccessAt}>{date(scan.lastSuccessAt)}</time>
      </small>
      {scan.errorCode && <small className="attention">Последнее обновление OSV не удалось</small>}
      {!compact && scan.findings.pageInfo.hasNextPage && (
        <small>Показаны первые 100 записей OSV.</small>
      )}
    </div>
  );
}
