import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


minio_route = Route("minio", deps=[])

plugin = PremierPlugin(throttler=Throttler())
