"use client";

import { useMutation, useQuery } from "@apollo/client/react";
import Link from "next/link";
import { createContext, useContext, useState, type ReactNode } from "react";
import { ErrorNotice, Pager } from "./account";
import { CompareToggle } from "./comparison";
import { useToast } from "./feedback";
import * as D from "./gql/graphql";
import { Modal } from "./modal";
import { useSession } from "./session";

const FollowContext = createContext<readonly string[] | undefined>(undefined);

export function PackageActionsProvider({ ids, children }: { ids: string[]; children: ReactNode }) {
  const session = useSession();
  const query = useQuery(D.VisibleFollowsDocument, {
    variables: { ids },
    skip: !session.data?.me || !ids.length,
    ssr: false,
    fetchPolicy: "network-only",
  });
  return (
    <FollowContext.Provider value={query.data?.myFollowedPackageIds}>
      {query.error && <ErrorNotice error={query.error} />}
      {children}
    </FollowContext.Provider>
  );
}

export function PackageActions({ name, id }: { name: string; id: string }) {
  const session = useSession();
  const followedIds = useContext(FollowContext);
  const following = followedIds?.includes(id) ?? false;
  const [picker, setPicker] = useState(false);
  const notify = useToast();
  const [follow, start] = useMutation(D.FollowPackageDocument);
  const [unfollow, stop] = useMutation(D.UnfollowPackageDocument);
  const checkingSession = session.loading && !session.data;
  return (
    <div className="package-tools" role="group" aria-label={`Действия с ${name}`}>
      <CompareToggle name={name} />
      {session.data?.me ? (
        <>
          <button
            className="secondary compact"
            aria-pressed={following}
            disabled={!followedIds || start.loading || stop.loading}
            onClick={async () => {
              try {
                await (following ? unfollow : follow)({
                  variables: { package: id },
                  refetchQueries: [D.VisibleFollowsDocument],
                  awaitRefetchQueries: true,
                });
                notify(following ? `Отслеживание ${name} отключено` : `Отслеживается ${name}`);
              } catch {
                /* The mutation error is shown alongside the action. */
              }
            }}
          >
            {following ? "Отслеживается" : "Отслеживать"}
          </button>
          <button
            className="secondary compact"
            aria-haspopup="dialog"
            onClick={() => setPicker(true)}
          >
            В подборку
          </button>
          {picker && <CollectionPicker id={id} name={name} onDismiss={() => setPicker(false)} />}
          <ErrorNotice error={start.error ?? stop.error} />
        </>
      ) : checkingSession ? (
        <>
          <button className="secondary compact" disabled>
            Отслеживать
          </button>
          <button className="secondary compact" disabled>
            В подборку
          </button>
        </>
      ) : (
        <>
          <Link
            className="button secondary compact"
            href="/account"
            title="Войти, чтобы отслеживать пакет"
          >
            Отслеживать
          </Link>
          <Link
            className="button secondary compact"
            href="/account"
            title="Войти, чтобы добавить в подборку"
          >
            В подборку
          </Link>
        </>
      )}
    </div>
  );
}

function CollectionPicker({
  id,
  name,
  onDismiss,
}: {
  id: string;
  name: string;
  onDismiss: () => void;
}) {
  const [after, setAfter] = useState<string>();
  const [selected, setSelected] = useState("");
  const { data, loading, error } = useQuery(D.CollectionsDocument, {
    variables: { after },
    fetchPolicy: "network-only",
  });
  const [add, added] = useMutation(D.AddToCollectionDocument);
  const notify = useToast();
  return (
    <Modal title={`${name} — в подборку`} onDismiss={onDismiss}>
      {data?.myCollections.nodes.length ? (
        <>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await add({ variables: { id: selected, package: id } });
                notify(`${name} добавлен в подборку`);
                onDismiss();
              } catch {
                /* shown below */
              }
            }}
          >
            <label>
              Подборка
              <select value={selected} onChange={(e) => setSelected(e.target.value)} required>
                <option value="">Выберите подборку</option>
                {data.myCollections.nodes.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="dialog-actions">
              <button disabled={!selected || added.loading}>Сохранить</button>
              <button type="button" className="secondary" onClick={onDismiss}>
                Отмена
              </button>
            </div>
          </form>
          <Pager
            after={after}
            next={data.myCollections.pageInfo}
            change={(value) => {
              setSelected("");
              setAfter(value);
            }}
          />
        </>
      ) : (
        <>
          {loading ? (
            <p role="status">Загрузка…</p>
          ) : (
            !error && (
              <Link className="button" href="/account">
                Создать подборку
              </Link>
            )
          )}
          <button className="secondary" onClick={onDismiss}>
            Закрыть
          </button>
        </>
      )}
      <ErrorNotice error={error ?? added.error} />
    </Modal>
  );
}
