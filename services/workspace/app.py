import strawberry
from radar_common.application import create_app
from radar_common.graphql import FederatedSchema

from services.workspace.auth_graphql import AuthMutation, AuthQuery
from services.workspace.domain_graphql import Package, context_getter
from services.workspace.domain_graphql import Query as DomainQuery
from services.workspace.personal import PersonalMutation, PersonalQuery


@strawberry.type
class Query(DomainQuery, AuthQuery, PersonalQuery):
    pass


@strawberry.type
class Mutation(AuthMutation, PersonalMutation):
    pass


schema = FederatedSchema(query=Query, mutation=Mutation, types=[Package], federation_version="2.7")
app = create_app(schema, "workspace", context_getter)
