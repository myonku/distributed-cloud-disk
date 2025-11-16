from typing import Literal
from lihil import Lihil, Request, Response, Route
from starlette.middleware.cors import CORSMiddleware
from lihil.problems import problem_solver

from endpoints.http_errors import InternalError
from kafka.kafka_client import KafkaClient
from repositories.redis_store import RedisManager
from endpoints.user import user
from config import read_config
from repositories.factory import redis, kafka


@problem_solver
def handle_error(req: Request, exc: Literal[500] | InternalError) -> Response:
    return Response(f"Internal Error: {str(exc)}", 500)


async def lifespan(app: Lihil):
    config = read_config("settings.toml", ".env")

    await redis.connect(config)
    await kafka.start(config)

    app.graph.register_singleton(redis, RedisManager)
    app.graph.register_singleton(kafka, KafkaClient)

    yield

    await kafka.stop()
    await redis.disconnect()


def app_factory() -> Lihil:
    app_config = read_config("settings.toml", ".env")
    sm_cfg = app_config.session_middleware

    root = Route(f"/api/v{app_config.API_VERSION}", deps=[])
    root.include_subroutes(user)
    root.sub("health").get(lambda: "ok")

    lhl = Lihil(root, app_config=app_config, lifespan=lifespan)
    lhl.add_middleware(
        [
            lambda app: CORSMiddleware(
                app,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ]
    )
    return lhl


app = app_factory()


if __name__ == "__main__":
    app.run(__file__)
