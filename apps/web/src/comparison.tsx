"use client";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { validName, compareURL } from "./url-state";

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
  return read(useSyncExternalStore(subscribe, snapshot, () => "[]"));
}

export function CompareToggle({ name }: { name: string }) {
  const names = useSelection();
  const selected = names.includes(name);
  const [message, setMessage] = useState("");
  return (
    <div className="compare-control">
      <button
        className="secondary compact"
        aria-pressed={selected}
        aria-label={`Сравнить ${name}`}
        onClick={() => {
          if (!selected && names.length === 4) {
            setMessage("Не более 4 пакетов");
            return;
          }
          save(selected ? names.filter((value) => value !== name) : [...names, name]);
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
  const names = useSelection();
  return <Link href={compareURL(names)}>Сравнение{names.length ? ` (${names.length})` : ""}</Link>;
}
export function RemoveComparison({ name, remaining }: { name: string; remaining: string[] }) {
  return (
    <Link
      className="remove-compare"
      aria-label={`Удалить ${name} из сравнения`}
      href={compareURL(remaining)}
      onClick={() => save(read(snapshot()).filter((value) => value !== name))}
    >
      ×
    </Link>
  );
}
export function CompareDock() {
  const names = useSelection();
  if (!names.length) return null;
  return (
    <aside className="compare-dock" aria-label="Выбрано для сравнения">
      <span>{names.length} / 4</span>
      <div className="compare-chips">
        {names.map((name) => (
          <button
            key={name}
            className="secondary compact"
            aria-label={`Убрать ${name}`}
            onClick={() => save(names.filter((value) => value !== name))}
          >
            {name} ×
          </button>
        ))}
      </div>
      <Link className="button" href={compareURL(names)}>
        Сравнить →
      </Link>
      <button className="secondary compact" onClick={() => save([])}>
        Очистить
      </button>
    </aside>
  );
}
