import type { ReactNode } from "react";
import type { CompareItemFragment } from "../../src/gql/graphql";
import { failedField, hasOsvResult, loadNearestScan } from "../../src/public-data";
import { PypiSnapshot, Scan, ProjectionNote, RepositorySummary } from "../../src/public-ui";

type Cell = string | { key: string; content: ReactNode };

export async function comparisonRows(
  items: (CompareItemFragment | null | undefined)[],
  error: unknown,
) {
  const aliases = ["a", "b", "c", "d"];
  const fallback = new Map(
    await Promise.all(
      items.map(async (item, i) => {
        const release = item?.current.nodes[0];
        const nearby =
          item?.source === "PYPI" &&
          release &&
          !hasOsvResult(release.scan) &&
          !failedField(error, "scan", aliases[i])
            ? await loadNearestScan(item.id, release.version)
            : null;
        return [aliases[i], nearby] as const;
      }),
    ),
  );
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
    row(
      "Версия PyPI",
      (item) => {
        const release = item.current.nodes[0];
        return {
          key: JSON.stringify([release?.version, Boolean(item.pypiFreshness.errorCode)]),
          content: (
            <PypiSnapshot
              version={release?.version}
              fetchedAt={release?.fetchedAt}
              freshness={item.pypiFreshness}
            />
          ),
        };
      },
      true,
    ),
    row("Python", (item) => item.requiresPython || "Не указано"),
    row("Лицензия", (item) => item.license || "Не указана"),
    row("Звёзды GitHub", (item) => {
      const projection = item.starProjection;
      return {
        key: JSON.stringify([projection.stars, projection.status]),
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
    row("Уязвимости OSV", (item, alias) => {
      const release = item.current.nodes[0];
      if (!release) return "Нет версии для проверки";
      const nearby = fallback.get(alias);
      if (failedField(error, "scan", alias) || nearby?.unavailable) return "OSV недоступен";
      const scan = nearby?.scan ?? release.scan;
      const failed = release.scan?.status === "FAILED";
      return {
        key: JSON.stringify([
          hasOsvResult(scan),
          failed,
          Boolean(scan?.errorCode),
          nearby?.scan?.version,
          scan?.findings.nodes.map((n) => n.id) ?? [],
          Boolean(scan?.findings.pageInfo.hasNextPage),
          scan?.fixes.nodes.map((f) => [f.advisoryId, f.version, f.historical]) ?? [],
          Boolean(scan?.fixes.pageInfo.hasNextPage),
        ]),
        content: (
          <Scan
            scan={scan}
            selected={release.version}
            nearby={Boolean(nearby?.scan)}
            failed={failed}
            compact
          />
        ),
      };
    }),
  ];
}
