"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, useSyncExternalStore, type ReactNode } from "react";
import { validName, compareURL, packageURL } from "./url-state";
import { useToast } from "./feedback";

const key = "radar-comparison";
let memory = "[]";
function snapshot() {
  try {
    return localStorage.getItem(key) ?? memory;
  } catch {
    return memory;
  }
}
function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("radar-compare", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("radar-compare", callback);
  };
}
function read(value: string): string[] {
  try {
    const names: unknown = JSON.parse(value);
    return Array.isArray(names)
      ? [
          ...new Set(
            names.filter((name): name is string => typeof name === "string" && validName(name)),
          ),
        ].slice(0, 4)
      : [];
  } catch {
    return [];
  }
}
function save(names: string[]) {
  memory = JSON.stringify(names);
  try {
    localStorage.setItem(key, memory);
  } catch {
    /* Current-tab memory remains usable. */
  }
  window.dispatchEvent(new Event("radar-compare"));
}
function useSelection() {
  const value = useSyncExternalStore<string | null>(subscribe, snapshot, () => null);
  return { names: value === null ? [] : read(value), ready: value !== null };
}

export function CompareToggle({ name }: { name: string }) {
  const notify = useToast();
  const { names, ready } = useSelection();
  const selected = names.includes(name);
  const [message, setMessage] = useState("");
  return (
    <div className="compare-control">
      <button
        className="secondary compact"
        disabled={!ready}
        aria-pressed={selected}
        aria-label={`Сравнить ${name}`}
        onClick={() => {
          if (!selected && names.length === 4) {
            setMessage("Не более 4 пакетов");
            return;
          }
          save(selected ? names.filter((value) => value !== name) : [...names, name]);
          notify(
            `Библиотека ${name} ${selected ? "удалена из сравнения" : "добавлена в сравнение"}`,
          );
          setMessage("");
        }}
      >
        {selected ? "✓ В сравнении" : "+ Сравнить"}
      </button>
      {message && (
        <span className="inline-error" role="alert">
          {message}
        </span>
      )}
    </div>
  );
}
export function CompareNav() {
  const { names } = useSelection();
  return <Link href={compareURL(names)}>Сравнение{names.length ? ` (${names.length})` : ""}</Link>;
}
function ShareComparison({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  const [manualURL, setManualURL] = useState("");
  return (
    <>
      <button
        type="button"
        className="secondary"
        onClick={async () => {
          const url = new URL(path, window.location.origin).href;
          try {
            await navigator.clipboard.writeText(url);
            setCopied(true);
            setManualURL("");
          } catch {
            setCopied(false);
            setManualURL(url);
          }
        }}
      >
        Скопировать ссылку на сравнение
      </button>
      <span role="status" className="share-status">
        {copied ? "Ссылка скопирована" : manualURL ? "Скопируйте ссылку из поля" : ""}
      </span>
      {manualURL && (
        <input
          readOnly
          aria-label="Ссылка на сравнение"
          value={manualURL}
          onFocus={(event) => event.target.select()}
        />
      )}
    </>
  );
}

export function ComparisonTable({
  names,
  rows,
}: {
  names: string[];
  rows: { label: string; equal: boolean; cells: ReactNode[] }[];
}) {
  const params = useSearchParams();
  const differences = names.length > 1 && params.get("differences") === "1";
  const path = compareURL(names, differences);
  const visible = differences ? rows.filter((row) => !row.equal) : rows;
  return (
    <>
      <div className="comparison-tools">
        {names.length > 1 && (
          <label className="comparison-filter">
            <input
              type="checkbox"
              checked={differences}
              aria-controls="package-comparison"
              onChange={() => window.history.pushState(null, "", compareURL(names, !differences))}
            />
            Скрыть строки с одинаковыми значениями
          </label>
        )}
        <span role="status" className="muted">
          Показано строк: {visible.length} из {rows.length}
        </span>
        <ShareComparison key={path} path={path} />
      </div>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Таблица сравнения">
        <table className="comparison-table" id="package-comparison">
          <thead>
            <tr>
              <th scope="col">Параметр</th>
              {names.map((name) => (
                <th scope="col" key={name}>
                  <Link href={packageURL(name)}>{name}</Link>
                  <Link
                    className="remove-compare"
                    aria-label={`Удалить ${name} из сравнения`}
                    href={compareURL(
                      names.filter((value) => value !== name),
                      differences,
                    )}
                    onClick={() => save(read(snapshot()).filter((value) => value !== name))}
                  >
                    ×
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                {row.cells}
              </tr>
            ))}
            {!visible.length && (
              <tr>
                <td colSpan={names.length + 1}>По доступным данным различий нет.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
