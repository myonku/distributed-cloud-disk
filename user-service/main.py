from typing import Literal
from lihil import Lihil, Request, Response, Route
from starlette.middleware.cors import CORSMiddleware
from lihil.problems import problem_solver
from lihil import HTTPException

from repositories.redis_store import RedisManager
from endpoints.user import user
from config import read_config

class InternalError(HTTPException[str]):
    "Internal Server Error"
    __status__ = 500


redis = RedisManager()

@problem_solver
def handle_error(req: Request, exc: Literal[500] | InternalError) -> Response:
    return Response(f"Internal Error: {str(exc)}", 500)


async def lifespan(app: Lihil):
    config = read_config("settings.toml", ".env")

    await redis.connect(config)
    app.graph.register_singleton(redis, RedisManager)

    yield

    await redis.disconnect()


def app_factory() -> Lihil:
    app_config = read_config("settings.toml", ".env")

    root = Route(
        f"/api/v{app_config.API_VERSION}", deps=[]
    )
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
