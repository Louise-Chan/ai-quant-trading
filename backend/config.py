"""应用配置"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    # 应用
    APP_NAME: str = "AI量化交易平台"
    DEBUG: bool = False
    
    # 数据库（无 MySQL 时可设 MYSQL_PASSWORD 或使用 SQLite）
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "ai_quant_trading"
    USE_SQLITE: bool = True  # 默认 SQLite 便于开发，生产可改用 MySQL
    
    # Redis（可选，暂用内存）
    REDIS_URL: str = ""
    
    # JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7天
    
    # CORS
    CORS_ORIGINS: list = ["*"]
    
    # 服务端口（gate-v2 默认 8081，避免与旧后端 8080 冲突）
    PORT: int = 8081
    
    @property
    def DATABASE_URL(self) -> str:
        if self.USE_SQLITE:
            # 使用绝对路径，避免工作目录不同导致数据库位置错误
            db_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(db_dir, "ai_quant.db")
            return f"sqlite:///{db_path.replace(os.sep, '/')}"
        return f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
    
    class Config:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
