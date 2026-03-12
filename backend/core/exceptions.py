"""自定义异常"""
from fastapi import HTTPException


def success_response(data=None, message: str = "操作成功", code: int = 200):
    """统一成功响应"""
    return {"success": True, "data": data, "message": message, "code": code}


def error_response(message: str = "操作失败", code: int = 400, data=None):
    """统一错误响应"""
    return {"success": False, "data": data, "message": message, "code": code}


class AppException(HTTPException):
    """应用异常"""
    def __init__(self, status_code: int = 400, detail: str = "操作失败"):
        super().__init__(status_code=status_code, detail=detail)
