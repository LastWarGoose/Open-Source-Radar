"""Transport primitives only; no shared domain entities."""

import asyncio
import base64
import binascii
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, ParamSpec, TypeVar

import strawberry
from graphql import GraphQLError
from opentelemetry import trace
from sqlalchemy import Select, SQLColumnExpression, func, literal, select, union_all
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased
from strawberry.dataloader import DataLoader

from radar_common.database import engine

T = TypeVar("T")
P = ParamSpec("P")


class FederatedSchema(strawberry.federation.Schema):
    def process_errors(self, errors: list[GraphQLError], execution_context: object = None) -> None:
        # Strawberry calls this even when the HTTP response is 200. Export only stable codes.
        span = trace.get_current_span()
        span.set_status(trace.StatusCode.ERROR)
        span.set_attribute("graphql.error.count", len(errors))
        known = {"BAD_USER_INPUT", "FORBIDDEN", "UNAUTHENTICATED", "NOT_FOUND", "UNAVAILABLE"}
        for error in errors:
            code = (error.extensions or {}).get("code")
            logging.getLogger("radar.graphql").warning(
                "graphql_error", extra={"error_type": code if code in known else "INTERNAL"}
            )


def invalid(message: str) -> GraphQLError:
    return GraphQLError(message, extensions={"code": "BAD_USER_INPUT"})


async def db_call[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except SQLAlchemyError as error:
        logging.getLogger("radar.database").error(
            "storage_unavailable", extra={"error_type": type(error).__name__}
        )
        raise GraphQLError("Storage unavailable", extensions={"code": "UNAVAILABLE"}) from None


def page_size(first: int) -> int:
    if not 1 <= first <= 100:
        raise invalid("first must be between 1 and 100")
    return first


def scope_key(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def encode_cursor(scope: str, *values: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([scope, *values]).encode()).decode()


def decode_cursor(cursor: str | None, scope: str, count: int = 1) -> list[str] | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 2048:
            raise ValueError
        values = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(values, list)
            or len(values) != count + 1
            or values[0] != scope
            or not all(isinstance(item, str) for item in values)
        ):
            raise ValueError
        return values[1:]
    except (ValueError, UnicodeError, binascii.Error):
        raise invalid("Invalid cursor or cursor does not match this query") from None


@strawberry.federation.type(shareable=True)
class PageInfo:
    has_next_page: bool
    end_cursor: str | None


@strawberry.type
class Connection(Generic[T]):  # noqa: UP046 -- Strawberry resolves __parameters__ at runtime.
    nodes: list[T]
    page_info: PageInfo


def connection[R](rows: list[R], first: int, cursor: Callable[[R], str]) -> Connection[R]:
    nodes = rows[:first]
    return Connection(
        nodes=nodes,
        page_info=PageInfo(
            has_next_page=len(rows) > first, end_cursor=cursor(nodes[-1]) if nodes else None
        ),
    )


@dataclass(frozen=True)
class PageKey:
    parent: str
    first: int
    after: str | None = None


def page_loader[R](
    model: type[R],
    query: Callable[[PageKey], Select[R]],
    order: Sequence[SQLColumnExpression],
    batch_first_pages: Callable[[list[PageKey]], list[list[R]] | None] | None = None,
) -> DataLoader[PageKey, list[R]]:
    """One bounded SQL UNION per batch, not one SQL roundtrip per parent."""

    def read(keys: list[PageKey]) -> list[list[R]]:
        if len(keys) == 1:
            key = keys[0]
            with Session(engine()) as session:
                return [list(session.scalars(query(key).order_by(*order).limit(key.first + 1)))]
        if batch_first_pages:
            result = batch_first_pages(keys)
            if result is not None:
                return result
        statements = [
            query(key)
            .order_by(*order)
            .add_columns(
                literal(i).label("_slot"), func.row_number().over(order_by=order).label("_position")
            )
            .limit(key.first + 1)
            .subquery()
            for i, key in enumerate(keys)
        ]
        combined = union_all(*(select(statement) for statement in statements)).subquery()
        entity = aliased(model, combined)
        groups: list[list[R]] = [[] for _ in keys]
        with Session(engine()) as session:
            for row, slot in session.execute(
                select(entity, combined.c._slot).order_by(combined.c._slot, combined.c._position)
            ):
                groups[slot].append(row)
        return groups

    async def load(keys: list[PageKey]) -> list[list[R]]:
        return await db_call(read, keys)

    return DataLoader(load_fn=load, max_batch_size=100)
