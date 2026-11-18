export const metadata = {
  title: "Техническая демонстрация",
  robots: { index: false, follow: false },
};
import { getClient } from "../../src/apollo-server";
import { DemoCatalogDocument } from "../../src/gql/graphql";
import { DemoPanel } from "../../src/demo-panel";

export const dynamic = "force-dynamic";

export default async function Page() {
  const { data } = await getClient().query({ query: DemoCatalogDocument });
  if (!data) throw new Error("Catalog returned no data");

  return (
    <>
      <section className="catalog" aria-labelledby="catalog-title">
        <div className="section-heading">
          <h1 id="catalog-title">Каталог</h1>
          <span className="count" aria-label={`Пакетов: ${data.packages.length}`}>
            {String(data.packages.length).padStart(2, "0")}
          </span>
        </div>
        <div className="package-list">
          {data.packages.map((item) => (
            <article className="package-row" key={item.id} data-testid="ssr-package">
              <h2>{item.name}</h2>
              {item.repository ? (
                <a className="repository" href={item.repository.url}>
                  {item.repository.fullName}
                  <span aria-hidden="true">↗</span>
                </a>
              ) : (
                <span>—</span>
              )}
              <span className="stars" aria-label={`Звёзды: ${item.repository?.stars ?? 0}`}>
                <span aria-hidden="true">★</span>{" "}
                {item.repository?.stars.toLocaleString("ru-RU") ?? "—"}
              </span>
            </article>
          ))}
        </div>
      </section>
      <DemoPanel />
    </>
  );
}
