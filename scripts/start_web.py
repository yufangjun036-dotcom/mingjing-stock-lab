"""备用云端启动入口：读取平台端口，不输出或传递任何密钥到命令参数。"""
import os
import sys
from pathlib import Path


def main():
    """验证监听端口，切换到项目目录，用当前 Python 启动 Streamlit。"""
    port = int(os.environ.get("PORT", "8501"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT 必须为 1–65535 之间的整数")
    # 固定项目根目录，避免平台工作目录差异导致 app.py 无法找到。
    os.chdir(Path(__file__).resolve().parents[1])
    # exec 替换当前进程，让云端停止信号直接传递给 Web 服务。
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address=0.0.0.0", f"--server.port={port}",
        "--server.headless=true", "--browser.gatherUsageStats=false",
    ])


if __name__ == "__main__":
    main()
