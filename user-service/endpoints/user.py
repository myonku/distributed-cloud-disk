import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


user = Route("user", deps=[])

plugin = PremierPlugin(throttler=Throttler())


@user.sub("login").post
async def login(): 
    """用户登录"""
    # TODO: 发布USER_LOGGED_IN事件


@user.sub("logout").post
async def logout(): 
    """用户登出"""
    # TODO: 发布USER_LOGGED_OUT事件

@user.sub("register").post
async def register(): 
    """用户注册"""
    # TODO: 发布Outbox -> dcd.user.events.v1，USER_CREATED


@user.sub("{user_id}").get
async def get_user_info(): 
    """获取用户信息"""


@user.sub("{user_id}").patch
async def update(): 
    """更新用户信息"""
    # TODO: 支持更新 email、display_name 等字段


@user.sub("{user_id}").delete
async def delete_user(): 
    """删除用户"""
    # TODO: 软删除


@user.sub("{user_id}/change-password").post
async def change_password(): 
    """修改用户密码"""


@user.sub("{user_id}/password-reset/request").post
async def password_reset_request():
    """发送重置邮件/验证码"""


@user.sub("{user_id}/password-reset/request").post
async def password_reset_cionfirm():
    """确认重置"""


@user.sub("{user_id}/quota").get
async def get_qutota_usage():
    """获取用户配额使用情况"""
