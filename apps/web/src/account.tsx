"use client";

import { useApolloClient, useMutation, useQuery } from "@apollo/client/react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import * as D from "./gql/graphql";
import { useSession } from "./session";
import { Modal } from "./modal";
export function AccountNav() {
  const { data } = useSession();
  return (
    <>
      <Link href="/account">{data?.me?.username ?? "Войти"}</Link>
      {data?.me?.role === "admin" && <Link href="/admin">Импорт</Link>}
    </>
  );
}
export function ErrorNotice({ error }: { error?: { message: string } }) {
  return error ? (
    <p role="alert" className="notice">
      {error.message}
    </p>
  ) : null;
}
export function Pager({
  next,
  after,
  change,
}: {
  next?: { hasNextPage: boolean; endCursor?: string | null };
  after?: string;
  change: (value: string | undefined) => void;
}) {
  return (
    <div className="personal-actions">
      {after && <button onClick={() => change(undefined)}>В начало</button>}
      {next?.hasNextPage && (
        <button onClick={() => change(next.endCursor ?? undefined)}>Далее →</button>
      )}
    </div>
  );
}
export function PrivateGate({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { data, loading, error } = useSession();
  if (loading && !data) return <p role="status">Загрузка…</p>;
  if (error) return <ErrorNotice error={error} />;
  if (!data?.me)
    return (
      <p className="notice">
        Войдите в аккаунт. <Link href="/account">Войти →</Link>
      </p>
    );
  if (admin && data.me.role !== "admin") return <p role="alert">Доступ только администратору.</p>;
  return children;
}
const accountSections = [
  { id: "collections", title: "Подборки", href: "/account" },
  { id: "following", title: "Отслеживание", href: "/account?section=following" },
  { id: "notifications", title: "Уведомления", href: "/account?section=notifications" },
] as const;

export function AccountPage({ section }: { section: string }) {
  const { data, loading, error } = useSession();
  const client = useApolloClient();
  const [logout, logoutState] = useMutation(D.LogoutDocument);
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState("");
  const [register, registerState] = useMutation(D.RegisterDocument, { fetchPolicy: "no-cache" });
  const [login, loginState] = useMutation(D.LoginDocument, { fetchPolicy: "no-cache" });
  const [recover, recoverState] = useMutation(D.RecoverAccountDocument, {
    fetchPolicy: "no-cache",
  });
  const busy = registerState.loading || loginState.loading || recoverState.loading;
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      if (mode === "register") {
        const result = await register({ variables: { username, password } });
        setRecovery(result.data?.register.recoveryCode ?? "");
        await client.clearStore();
      } else if (mode === "recover") {
        const result = await recover({ variables: { username, password, code } });
        setRecovery(result.data?.recoverAccount ?? "");
        await client.clearStore();
      } else {
        await login({ variables: { username, password } });
        await client.clearStore();
        window.location.reload();
      }
      setPassword("");
      setCode("");
    } catch {
      /* Apollo exposes the error below. */
    }
  }
  if (recovery)
    return (
      <section className="catalog auth-panel">
        <h1>Код восстановления</h1>
        <p>Сохраните код. Он показывается один раз и заменяется после использования.</p>
        <code className="recovery-code" data-testid="recovery-code">
          {recovery}
        </code>
        <a className="button" href="/account">
          Код сохранён →
        </a>
      </section>
    );
  if (loading && !data) return <p role="status">Загрузка…</p>;
  if (data?.me) {
    const active = accountSections.find((item) => item.id === section) ?? accountSections[0];
    return (
      <div className="account-layout">
        <aside className="account-sidebar">
          <header className="account-identity">
            <p>Личный кабинет</p>
            <h1>{data.me.username}</h1>
          </header>
          <nav aria-label="Разделы личного кабинета">
            {accountSections.map((item) => (
              <Link
                key={item.id}
                href={item.href}
                scroll={false}
                aria-current={active === item ? "page" : undefined}
              >
                {item.title}
                <span aria-hidden="true">→</span>
              </Link>
            ))}
          </nav>
          <button
            className="account-logout"
            disabled={logoutState.loading}
            onClick={async () => {
              try {
                await logout();
                await client.clearStore();
                window.location.reload();
              } catch {
                /* shown below */
              }
            }}
          >
            Выйти
          </button>
          <ErrorNotice error={logoutState.error} />
        </aside>
        <section key={active.id} className="account-panel" aria-labelledby="account-section-title">
          <h2 id="account-section-title">{active.title}</h2>
          {active.id === "collections" && <Collections />}
          {active.id === "following" && <Follows />}
          {active.id === "notifications" && <Notifications />}
        </section>
      </div>
    );
  }
  return (
    <section className="catalog auth-panel">
      <h1>
        {mode === "register"
          ? "Регистрация"
          : mode === "recover"
            ? "Восстановление доступа"
            : "Вход"}
      </h1>
      <form onSubmit={submit} className="personal-form">
        <label>
          Логин
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            pattern="[A-Za-z0-9][A-Za-z0-9_-]{2,39}"
            required
            maxLength={40}
          />
        </label>
        {mode === "recover" && (
          <label>
            Код восстановления
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="off"
              required
              maxLength={128}
            />
          </label>
        )}
        <label>
          {mode === "recover" ? "Новый пароль" : "Пароль"}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={12}
            maxLength={128}
            required
          />
        </label>
        <span className="muted">Пароль — от 12 символов.</span>
        <button disabled={busy}>
          {mode === "register"
            ? "Создать аккаунт"
            : mode === "recover"
              ? "Сменить пароль"
              : "Войти"}
        </button>
      </form>
      <ErrorNotice error={registerState.error ?? loginState.error ?? recoverState.error ?? error} />
      <div className="personal-actions">
        {[
          ["login", "Вход"],
          ["register", "Регистрация"],
          ["recover", "Забыли пароль?"],
        ]
          .filter(([key]) => key !== mode)
          .map(([key, label]) => (
            <button
              className="secondary"
              key={key}
              onClick={() => {
                setMode(key);
                registerState.reset();
                loginState.reset();
                recoverState.reset();
              }}
            >
              {label}
            </button>
          ))}
      </div>
    </section>
  );
}
function Collections() {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [after, setAfter] = useState<string>();
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const activeRow = useRef<HTMLLIElement>(null);
  const collections = useQuery(D.CollectionsDocument, {
    variables: { after },
    fetchPolicy: "network-only",
  });
  const [create, created] = useMutation(D.CreateCollectionDocument);
  const [remove, removed] = useMutation(D.DeleteCollectionDocument);
  useEffect(() => {
    if (!selected) return;
    function outside(e: Event) {
      if (e.target instanceof Node && activeRow.current && !activeRow.current.contains(e.target))
        setSelected(null);
    }
    function escape(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      activeRow.current?.querySelector<HTMLButtonElement>(".collection-toggle")?.focus();
      setSelected(null);
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [selected]);

  const rows = collections.data?.myCollections.nodes ?? [];
  // A new collection can sort beyond the first cursor page.
  const visible =
    selected && !rows.some((row) => row.id === selected.id) ? [...rows, selected] : rows;
  return (
    <>
      <button
        onClick={() => {
          setSelected(null);
          setName("");
          created.reset();
          setCreating(true);
        }}
      >
        Создать подборку
      </button>
      {creating && (
        <Modal title="Новая подборка" onDismiss={() => setCreating(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const result = await create({ variables: { name: name.trim() } });
                setCreating(false);
                setAfter(undefined);
                setSelected(result.data?.createCollection ?? null);
                await collections.refetch({ after: undefined });
              } catch {
                /* shown in the form or list */
              }
            }}
          >
            <label>
              Название подборки
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
                required
              />
            </label>
            <div className="dialog-actions">
              <button disabled={created.loading || !name.trim()}>Создать</button>
              <button type="button" className="secondary" onClick={() => setCreating(false)}>
                Отмена
              </button>
            </div>
            <ErrorNotice error={created.error} />
          </form>
        </Modal>
      )}
      <ErrorNotice error={collections.error ?? removed.error} />
      {visible.length > 0 && (
        <ul className="collection-list">
          {visible.map((row) => {
            const open = selected?.id === row.id;
            return (
              <li key={row.id} ref={open ? activeRow : undefined}>
                <button
                  className="collection-toggle secondary"
                  aria-expanded={open}
                  aria-controls={open ? `collection-${row.id}` : undefined}
                  onClick={() => setSelected((current) => (current?.id === row.id ? null : row))}
                >
                  {row.name}
                  <span aria-hidden="true">{open ? "−" : "+"}</span>
                </button>
                {open && (
                  <div className="collection-body" id={`collection-${row.id}`}>
                    <CollectionContents id={row.id} />
                    <CollectionDelete
                      name={row.name}
                      busy={removed.loading}
                      onDelete={async () => {
                        try {
                          await remove({ variables: { id: row.id } });
                          setSelected(null);
                          await collections.refetch();
                        } catch {
                          /* shown above */
                        }
                      }}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <Pager
        after={after}
        next={collections.data?.myCollections.pageInfo}
        change={(v) => {
          setSelected(null);
          setAfter(v);
        }}
      />
    </>
  );
}

function CollectionDelete({
  name,
  busy,
  onDelete,
}: {
  name: string;
  busy: boolean;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="collection-menu">
      <button className="secondary compact" aria-expanded={open} onClick={() => setOpen(!open)}>
        Действия
      </button>
      {open && (
        <button
          className="compact delete-action"
          aria-label={`Удалить подборку ${name}`}
          disabled={busy}
          onClick={onDelete}
        >
          Удалить
        </button>
      )}
    </div>
  );
}
function CollectionContents({ id }: { id: string }) {
  const [after, setAfter] = useState<string>();
  const query = useQuery(D.CollectionItemsDocument, {
    variables: { id, after },
    fetchPolicy: "network-only",
  });
  const [remove, state] = useMutation(D.RemoveFromCollectionDocument);
  return (
    <div>
      <ErrorNotice error={query.error ?? state.error} />
      <ul className="personal-list">
        {query.data?.collection?.items.nodes.map((row, index) => (
          <li key={row.package?.id ?? index}>
            {row.package ? (
              <>
                <Link href={`/packages/${row.package.name}`}>{row.package.name}</Link>
                <button
                  disabled={state.loading}
                  aria-label={`Убрать ${row.package.name}`}
                  onClick={async () => {
                    try {
                      await remove({ variables: { id, package: row.package!.id } });
                      await query.refetch();
                    } catch {
                      /* shown */
                    }
                  }}
                >
                  Убрать
                </button>
              </>
            ) : (
              "Пакет недоступен"
            )}
          </li>
        ))}
      </ul>
      {query.data?.collection?.items.nodes.length === 0 && <p>В подборке пока нет пакетов.</p>}
      <Pager after={after} next={query.data?.collection?.items.pageInfo} change={setAfter} />
    </div>
  );
}
function Follows() {
  const [after, setAfter] = useState<string>();
  const query = useQuery(D.FollowsDocument, { variables: { after }, fetchPolicy: "network-only" });
  const [remove, state] = useMutation(D.UnfollowPackageDocument);
  return (
    <>
      <ErrorNotice error={query.error ?? state.error} />
      <ul className="personal-list">
        {query.data?.myFollows.nodes.map((row, index) => (
          <li key={row.package?.id ?? index}>
            {row.package ? (
              <>
                <Link href={`/packages/${row.package.name}`}>{row.package.name}</Link>
                <span>{row.version}</span>
                <button
                  disabled={state.loading}
                  aria-label={`Не отслеживать ${row.package.name}`}
                  onClick={async () => {
                    try {
                      await remove({ variables: { package: row.package!.id } });
                      await query.refetch();
                    } catch {
                      /* shown */
                    }
                  }}
                >
                  Не отслеживать
                </button>
              </>
            ) : (
              "Пакет недоступен"
            )}
          </li>
        ))}
      </ul>
      {query.data?.myFollows.nodes.length === 0 && (
        <p>
          Выберите пакет в <Link href="/#catalog">каталоге</Link>, чтобы следить за обновлениями.
        </p>
      )}
      <Pager after={after} next={query.data?.myFollows.pageInfo} change={setAfter} />
    </>
  );
}
function Notifications() {
  const [after, setAfter] = useState<string>();
  const query = useQuery(D.NotificationsDocument, {
    variables: { after },
    fetchPolicy: "network-only",
    pollInterval: 15000,
  });
  const [read, state] = useMutation(D.ReadNotificationDocument);
  return (
    <>
      <ErrorNotice error={query.error ?? state.error} />
      <ul className="personal-list">
        {query.data?.myNotifications.nodes.map((row) => (
          <li key={row.id}>
            <span>{row.message}</span>
            {!row.readAt ? (
              <button
                disabled={state.loading}
                onClick={async () => {
                  try {
                    await read({ variables: { id: row.id } });
                    await query.refetch();
                  } catch {
                    /* shown */
                  }
                }}
              >
                Прочитано
              </button>
            ) : (
              <span className="muted">Прочитано</span>
            )}
          </li>
        ))}
      </ul>
      {query.data?.myNotifications.nodes.length === 0 && <p>Новых уведомлений нет.</p>}
      <Pager after={after} next={query.data?.myNotifications.pageInfo} change={setAfter} />
    </>
  );
}
