import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


minio = Route("minio", deps=[])

plugin = PremierPlugin(throttler=Throttler())
