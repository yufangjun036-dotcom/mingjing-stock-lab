"""服务端配置：环境变量优先，本地密钥文件仅补充缺项。"""
import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path
import certifi
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    """隐藏密钥的对象表示，避免日志意外泄露。"""
    fuyao_api_key: str = field(repr=False)
    openai_api_key: str = field(default="", repr=False)
    ca_file: str | None = None


def load_settings():
    """从环境或本地文件读取配置；不输出秘密值。"""
    for name in (".env.local", ".env.fuyao"):
        load_dotenv(ROOT / name, override=False)
    return Settings(fuyao_api_key=os.getenv("FUYAO_API_KEY", ""),
                    openai_api_key=os.getenv("OPENAI_API_KEY", ""),
                    ca_file=os.getenv("APP_CA_FILE") or None)


def build_ssl_context(settings):
    """使用有效 CA 并保留证书与主机名校验；兼容本地和云端。"""
    return ssl.create_default_context(cafile=settings.ca_file or certifi.where())
