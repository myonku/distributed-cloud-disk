import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


gateway = Route("gateway", deps=[])

plugin = PremierPlugin(throttler=Throttler())


@gateway.sub("/session").post
async def session():
    """创建网关会话，或返回已有会话信息（网关）用于客户端自检"""


@gateway.sub("/handshake/ticket").get
async def get_handshake_ticket():
    """获取握手票据，用于网关向客户端分发用于和其他服务握手的临时凭据"""


@gateway.sub("/discovery/catalog").get
async def get_discovery_catalog():
    """获取服务发现目录，返回可用的服务列表"""


@gateway.sub("/discovery/reslove").get
async def get_optimal_server():
    """按服务名称、作用域等自动解析并返回最优服务端点"""
