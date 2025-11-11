from lihil import HTTPException


class InternalError(HTTPException[str]):
    "Internal Server Error"

    __status__ = 500
