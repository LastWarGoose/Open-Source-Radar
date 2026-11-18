"use client";

import { useMutation, useQuery, useSubscription } from "@apollo/client/react";
import { useState } from "react";
import { AdvanceDemoDocument, DemoPackageDocument, PackageUpdatedDocument } from "./gql/graphql";

const variables = { id: "pypi:fastapi" };

export function DemoPanel() {
  const [listening, setListening] = useState(true);
  const [eventRevision, setEventRevision] = useState<number | null>(null);
  const [eventRepository, setEventRepository] = useState("");
  const query = useQuery(DemoPackageDocument, { variables, fetchPolicy: "cache-and-network" });
  const [advance, mutation] = useMutation(AdvanceDemoDocument, { variables });
  const subscription = useSubscription(PackageUpdatedDocument, {
    variables,
    skip: !listening,
    onData: ({ data }) => {
      const event = data.data?.packageUpdated;
      if (event) {
        setEventRevision(event.demoRevision);
        setEventRepository(event.repository?.fullName ?? "Нет данных");
        // On every subscription/reconnect snapshot, query the current state.
        void query.refetch().catch(() => undefined); // The query error is rendered below.
      }
    },
  });
  const error = query.error ?? mutation.error ?? subscription.error;

  return (
    <details className="activity">
      <summary>
        <span className="activity-title">Обновления</span>
        <span className="status" role="status">
          <span className={listening ? "status-mark" : "status-mark paused"} aria-hidden="true" />
          {!listening
            ? "Пауза"
            : subscription.loading
              ? "Подключение…"
              : subscription.error
                ? "Нет связи"
                : "LIVE"}
        </span>
      </summary>
      <div className="activity-content">
        <dl>
          <div>
            <dt>Данные</dt>
            <dd data-testid="query-revision">{query.data?.package?.demoRevision ?? "—"}</dd>
          </div>
          <div>
            <dt>Событие</dt>
            <dd data-testid="event-revision" aria-live="polite">
              {eventRevision ?? "—"}
            </dd>
          </div>
          <div>
            <dt>GitHub</dt>
            <dd data-testid="event-repository">{eventRepository || "—"}</dd>
          </div>
        </dl>
        <div className="buttons">
          <button className="secondary" onClick={() => setListening(!listening)}>
            {listening ? "Пауза" : "Продолжить"}
          </button>
          <button
            disabled={mutation.loading || query.loading}
            onClick={() => {
              void advance().catch(() => undefined);
            }}
          >
            Обновить
          </button>
        </div>
        {error && (
          <p role="alert" className="error">
            Не удалось получить данные.
          </p>
        )}
      </div>
    </details>
  );
}
