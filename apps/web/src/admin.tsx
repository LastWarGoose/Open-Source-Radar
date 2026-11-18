"use client";

import { useMutation, useQuery, useSubscription } from "@apollo/client/react";
import { useState } from "react";
import { PrivateGate, ErrorNotice } from "./account";
import * as D from "./gql/graphql";

const labels: Record<string, string> = {
  queued: "В очереди",
  running: "В работе",
  succeeded: "Завершён",
  failed: "Ошибка",
};
export function AdminPage() {
  return (
    <PrivateGate admin>
      <Imports />
    </PrivateGate>
  );
}
function Imports() {
  const [names, setNames] = useState("");
  const [after, setAfter] = useState<string>();
  const [selected, setSelected] = useState("");
  const [requestKey, setRequestKey] = useState<string>();
  const query = useQuery(D.AdminJobsDocument, {
    variables: { after },
    fetchPolicy: "network-only",
    pollInterval: 15000,
  });
  const [start, state] = useMutation(D.StartImportDocument);
  return (
    <section className="catalog">
      <h1>Импорт</h1>
      <form
        className="personal-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const key = requestKey ?? crypto.randomUUID();
          setRequestKey(key);
          try {
            const result = await start({
              variables: {
                key,
                targets: names
                  .split(/[\s,]+/)
                  .filter(Boolean)
                  .map((name) => ({ name })),
              },
            });
            setSelected(result.data?.requestImport.id ?? "");
            await query.refetch();
          } catch {
            /* shown below; retry preserves key */
          }
        }}
      >
        <label>
          Пакеты PyPI — до 20
          <textarea
            value={names}
            onChange={(e) => {
              setNames(e.target.value);
              setRequestKey(undefined);
            }}
            required
            maxLength={2000}
            placeholder="requests httpx"
          />
        </label>
        <button disabled={state.loading}>Запустить импорт</button>
      </form>
      <ErrorNotice error={state.error ?? query.error} />
      {selected && <Progress key={selected} id={selected} />}
      <h2>Задания</h2>
      <ul className="personal-list">
        {query.data?.importJobs.nodes.map((job) => (
          <li key={job.id}>
            <button onClick={() => setSelected(job.id)}>
              {job.source} · {labels[job.status] ?? job.status} · {job.processed}
            </button>
            <time>{new Date(job.createdAt).toLocaleString("ru")}</time>
          </li>
        ))}
      </ul>
      <div className="personal-actions">
        {after && <button onClick={() => setAfter(undefined)}>В начало</button>}
        {query.data?.importJobs.pageInfo.hasNextPage && (
          <button onClick={() => setAfter(query.data?.importJobs.pageInfo.endCursor ?? undefined)}>
            Далее →
          </button>
        )}
      </div>
    </section>
  );
}
function Progress({ id }: { id: string }) {
  const [retry, state] = useMutation(D.ResumeImportDocument);
  const query = useQuery(D.AdminJobDocument, {
    variables: { id },
    fetchPolicy: "network-only",
    pollInterval: 3000,
  });
  const subscription = useSubscription(D.ImportProgressDocument, {
    variables: { id },
    onData: () => {
      void query.refetch();
    },
  });
  // Query runs after mount/reconnect and remains a fallback if the socket is unavailable.
  const job = query.data?.importJob;
  return (
    <section className="job-progress" aria-label="Прогресс импорта">
      <h2>Прогресс</h2>
      <code>{id}</code>
      <p role="status">
        {job ? `${labels[job.status] ?? job.status} · обработано ${job.processed}` : "Загрузка…"}
      </p>
      {job?.errorCode && <p role="alert">{job.errorCode}</p>}
      {subscription.error && (
        <p className="muted">Соединение прервано. Статус обновляется запросами.</p>
      )}
      <ErrorNotice error={query.error ?? state.error} />
      {job?.status === "failed" && job.canResume && (
        <button
          disabled={state.loading}
          onClick={async () => {
            try {
              await retry({ variables: { id } });
              await query.refetch();
            } catch {
              /* shown */
            }
          }}
        >
          Повторить импорт
        </button>
      )}
    </section>
  );
}
