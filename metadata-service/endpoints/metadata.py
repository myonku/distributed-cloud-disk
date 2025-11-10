import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


metadata = Route("metadata", deps=[])

plugin = PremierPlugin(throttler=Throttler())
