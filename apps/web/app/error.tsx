"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <>
      <section className="catalog empty-state" role="alert">
        <h1>Данные недоступны</h1>
        <button onClick={reset}>Повторить</button>
      </section>
    </>
  );
}
