"""应用配置"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    # 应用
    APP_NAME: str = "SilentSigma 套利者"
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
    def DATA_DIR(self) -> str:
        """运行期可写目录：
        - 开发态/未设置环境变量：仍落到 backend 源码目录（保持旧行为）。
        - 安装态（Electron 打包）：由主进程注入 SILENTSIGMA_DATA_DIR 指向
          %LOCALAPPDATA%\\SilentSigma 等用户可写目录，避免 Program Files 权限问题。
        """
        env_dir = os.environ.get("SILENTSIGMA_DATA_DIR", "").strip()
        if env_dir:
            os.makedirs(env_dir, exist_ok=True)
            return env_dir
        return os.path.dirname(os.path.abspath(__file__))

    @property
    def DATABASE_URL(self) -> str:
        if self.USE_SQLITE:
            db_path = os.path.join(self.DATA_DIR, "ai_quant.db")
            return f"sqlite:///{db_path.replace(os.sep, '/')}"
        return f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
    
    class Config:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
