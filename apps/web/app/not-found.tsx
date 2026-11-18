import Link from "next/link";
export default function NotFound() {
  return (
    <>
      <section className="catalog empty-state">
        <h1>Пакет или страница не найдены</h1>
        <Link href="/#catalog">В каталог →</Link>
      </section>
    </>
  );
}
