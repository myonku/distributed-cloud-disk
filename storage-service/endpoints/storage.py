import datetime as dt
from lihil import Param, Route, Annotated, status
from lihil.plugins.premier import PremierPlugin
from premier import Throttler


storage = Route("storage", deps=[])

plugin = PremierPlugin(throttler=Throttler())

# region 上传端点
@storage.sub("upload-sessions/{session_id}/parts").post
async def upload_part():
    """分配指定/下一个分片的预签名上传 URL（multipart 上传）"""


@storage.sub("upload-sessions/{session_id}/parts/{index}/commit").post
async def upload_part_commit():
    """客户端上传完成后回调提交，服务端读取 ETag/Size 校验并记录"""


@storage.sub("upload-sessions/{session_id}/parts").get
async def upload_part_status():
    """查询指定分片的上传状态（是否已上传，ETag/Size）"""


@storage.sub("upload-sessions/{session_id}/merge").post
async def upload_part_merge():
    """合并所有分片，完成 Multipart Upload"""


@storage.sub("upload-sessions/{session_id}/abort").post
async def upload_part_abort():
    """中止 Multipart Upload，删除已上传的分片"""


# endregion

# region 文件端点

@storage.sub("files/{file_id}/download").post
async def file_download():
    """生成文件下载的预签名 URL"""

@storage.sub("files/{file_id}").delete
async def file_delete():
    """删除文件及其元数据"""

# endregion


# region 对象端点

@storage.sub("objects/{object_key}/verify").post
async def object_verify():
    """二次校验对象完整性（可用于巡检/修复）"""

@storage.sub("objects/usage").get
async def object_usage():
    """对象存储维度的用量统计（快速近似或离线聚合）"""

# endregion


# region 桶配置/管理端点

@storage.sub("buckets/{user_id}/ensure").post
async def bucket_ensure():
    """为用户预配桶/策略（来自 USER_CREATED 事件触发或手动）"""

@storage.sub("buckets/{bucket}/lifecycle").post
async def bucket_lifecycle_configure():
    """配置桶的生命周期规则（自动过期删除）"""

# endregion
