export default function Loading() {
  return (
    <>
      <section className="catalog loading-state" role="status" aria-live="polite">
        Загрузка…
        <div className="loading-line" />
      </section>
    </>
  );
}
