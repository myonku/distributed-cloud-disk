import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler



user = Route("user", deps=[])

plugin = PremierPlugin(throttler=Throttler())
