"use client";

import Form from "next/form";
import { useState, type ReactNode } from "react";
import type { catalogState } from "./url-state";

export function CatalogFilters({
  state,
  children,
}: {
  state: ReturnType<typeof catalogState>;
  children: ReactNode;
}) {
  const [term, setTerm] = useState(state.q);
  const [sort, setSort] = useState<string>(state.sort);
  return (
    <Form className="filters" action="/#catalog" scroll={false} role="search">
      <label className="search-field">
        Поиск
        <input
          name="q"
          type="search"
          maxLength={200}
          value={term}
          placeholder="Название или описание"
          onChange={(event) => {
            const value = event.target.value;
            setTerm(value);
            if (!value.trim() && sort === "RELEVANCE") setSort("STARS_DESC");
          }}
        />
      </label>
      <label>
        Лицензия
        {children}
      </label>
      <label>
        Версии
        <select name="releases" defaultValue={state.releases}>
          <option value="">Все</option>
          <option value="yes">Есть в каталоге</option>
          <option value="no">Не загружены</option>
        </select>
      </label>
      <label>
        Сортировка
        <select
          name="sort"
          value={sort}
          aria-describedby={sort === "RELEVANCE" ? "relevance-hint" : undefined}
          onChange={(event) => setSort(event.target.value)}
        >
          <option value="STARS_DESC">По звёздам GitHub ↓</option>
          <option value="RELEVANCE" disabled={!term.trim()}>
            По релевантности запроса
          </option>
          <option value="NAME_ASC">По названию</option>
          <option value="UPDATED_DESC">По дате обновления</option>
        </select>
      </label>
      <input type="hidden" name="size" value={state.size} />
      <button type="submit">Найти</button>
      {sort === "RELEVANCE" && (
        <small className="relevance-hint" id="relevance-hint">
          Выше точное название, затем совпадения в названии и описании.
        </small>
      )}
    </Form>
  );
}
