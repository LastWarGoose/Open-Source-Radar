import hashlib
import hmac
import os
from uuid import UUID

from graphql import GraphQLError

DEV_ACTORS = (
    UUID("10000000-0000-4000-8000-000000000001"),
    UUID("10000000-0000-4000-8000-000000000002"),
)


def dev_token(secret: str, actor: UUID) -> str:
    return hmac.new(
        secret.encode(), ("workspace:" + str(actor)).encode(), hashlib.sha256
    ).hexdigest()


def actor_for_token(token: str) -> UUID:
    secret = os.environ.get("DEV_ADMIN_TOKEN", "")
    if secret:
        for actor in DEV_ACTORS:
            if hmac.compare_digest(token.encode(), dev_token(secret, actor).encode()):
                return actor
    raise GraphQLError("Войдите в аккаунт заново", extensions={"code": "UNAUTHENTICATED"})
