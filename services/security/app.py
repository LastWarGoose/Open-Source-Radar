from radar_common.application import create_app
from radar_common.graphql import FederatedSchema

from services.security.domain_graphql import Package, Query, Release, context_getter
from services.security.import_api import Mutation

schema = FederatedSchema(
    query=Query, mutation=Mutation, types=[Release, Package], federation_version="2.7"
)
app = create_app(schema, "security", context_getter)
