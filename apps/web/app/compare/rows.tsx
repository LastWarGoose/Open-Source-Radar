import type { ReactNode } from "react";
import type { CompareItemFragment } from "../../src/gql/graphql";
import { failedField } from "../../src/public-data";
import { date, Freshness, ProjectionNote, RepositorySummary } from "../../src/public-ui";

type Cell = string | { key: string; content: ReactNode };

export function comparisonRows(items: (CompareItemFragment | null | undefined)[], error: unknown) {
  const aliases = ["a", "b", "c", "d"];
  function row(
    label: string,
    format: (item: CompareItemFragment, alias: string) => Cell,
    identifyMissing = false,
  ) {
    const cells = items.map((item, i) => {
      if (item?.source === "PYPI") return format(item, aliases[i]);
      if (!identifyMissing) return "—";
      return failedField(error, aliases[i]) ? "Данные недоступны" : "Пакет не найден";
    });
    const keys = cells.map((cell) => (typeof cell === "string" ? cell : cell.key));
    return {
      label,
      equal:
        keys.every((key) => key === keys[0]) &&
        !(identifyMissing && items.every((item) => item?.source !== "PYPI")),
      cells: cells.map((cell, i) => (
        <td key={aliases[i]}>{typeof cell === "string" ? cell : cell.content}</td>
      )),
    };
  }
  return [
    row("Описание пакета", (item) => item.summary || "Нет описания"),
    row("Версия в каталоге", (item) => item.current.nodes[0]?.version ?? "Не загружена", true),
    row("Python", (item) => item.requiresPython || "Не указано"),
    row("Лицензия", (item) => item.license || "Не указана"),
    row("Звёзды GitHub", (item) => {
      const projection = item.starProjection;
      return {
        key: JSON.stringify([
          projection.stars,
          projection.checkedAt && [
            date(projection.checkedAt),
            date(projection.projectedAt),
            projection.lagSeconds,
            projection.status,
          ],
        ]),
        content: (
          <>
            {projection.stars?.toLocaleString("ru-RU") ?? "Не получены"}
            <small>
              <ProjectionNote value={projection} />
            </small>
          </>
        ),
      };
    }),
    row("Репозитории", (item, alias) => {
      const links = item.repositories;
      if (!links?.nodes.length) {
        if (
          failedField(error, "repositories", alias) ||
          failedField(error, "githubFreshness", alias)
        )
          return "GitHub недоступен";
        return item.githubFreshness?.status === "SUCCESS" ? "Нет подтверждённых" : "Нет данных";
      }
      return {
        key: JSON.stringify([
          links.nodes.map((link) => (link.repository ? [link.repository.id, link.status] : null)),
          links.pageInfo.hasNextPage,
        ]),
        content: (
          <>
            {links.nodes.map((link, i) => (
              <RepositorySummary key={link.repository?.id ?? i} link={link} />
            ))}
            {links.pageInfo.hasNextPage && <small>Показаны первые 5 репозиториев.</small>}
          </>
        ),
      };
    }),
    row("OSV · выбранная версия", (item, alias) => {
      const scan = item.current.nodes[0]?.scan;
      if (!scan && failedField(error, "scan", alias)) return "Недоступно";
      let status = "Не проверено";
      const findings =
        scan?.status === "SUCCESS" ? scan.findings.nodes.map(({ id }) => id).sort() : [];
      if (scan?.status === "SUCCESS") {
        const count = findings.length;
        status = count
          ? `Найдено: ${count}${scan.findings.pageInfo.hasNextPage ? "+" : ""}`
          : "Совпадений нет";
      } else if (scan?.status === "STALE") status = "Результат устарел";
      else if (scan?.status === "FAILED") status = "Ошибка проверки";
      if (!findings.length && !scan?.lastSuccessAt) return status;
      const checked = scan?.lastSuccessAt ? date(scan.lastSuccessAt) : "";
      return {
        key: JSON.stringify([status, findings, checked]),
        content: (
          <>
            {findings.length ? (
              <details>
                <summary>{status}</summary>
                <ul>
                  {findings.map((id) => (
                    <li key={id}>{id}</li>
                  ))}
                </ul>
              </details>
            ) : (
              status
            )}
            {checked && <small className="muted">{checked}</small>}
          </>
        ),
      };
    }),
    row("Обновление PyPI", (item) => ({
      key: JSON.stringify([item.pypiFreshness.status, date(item.pypiFreshness.lastSuccessAt)]),
      content: <Freshness value={item.pypiFreshness} />,
    })),
  ];
}
