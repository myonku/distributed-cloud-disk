import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


metadata = Route("metadata", deps=[])

plugin = PremierPlugin(throttler=Throttler())


@metadata.sub("upload-sessions").post
async def upload_sessions():
    """生成上传会话标"""


@metadata.sub("upload-sessions/{session_id}").get
async def get_upload_session():
    """获取上传会话"""


@metadata.sub("upload-sessions/{session_id}/complete").post
async def complete_upload_session():
    """完成上传会话"""


@metadata.sub("files").get
async def list_files():
    """获取目录文件信息"""


@metadata.sub("files/{file_id}").get
async def get_file_metadata():
    """获取文件元数据"""


@metadata.sub("directories").post
async def create_directory():
    """创建目录节点"""


@metadata.sub("files/{file_id}/rename").post
async def rename_file():
    """重命名文件或目录节点"""


@metadata.sub("files/{file_id}/move").post
async def move_file():
    """移动文件或目录节点"""


@metadata.sub("files/{file_id}").delete
async def delete_file():
    """删除文件或目录节点"""
