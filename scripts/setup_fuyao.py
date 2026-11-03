"""在用户自己的终端中隐藏输入扶摇密钥，仅保存到本项目私密配置文件。"""

import getpass
import os
from pathlib import Path
import sys


def main() -> None:
    """读取隐藏输入并保存；取消或无效输入时保留原文件，不输出密钥。"""
    if not sys.stdin.isatty():
        print("请在交互终端运行本脚本，未读取或保存密钥。")
        return
    destination = Path(__file__).resolve().parent.parent / ".env.fuyao"
    if destination.is_symlink():
        print("配置路径是符号链接，已停止保存。")
        return
    try:
        secret = getpass.getpass("请输入扶摇密钥（粘贴后不会显示），然后按回车：").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消，未修改配置。")
        return
    # 禁止空白及多行内容，避免把多段文本误当作单个密钥写入环境配置。
    if not secret or any(character.isspace() for character in secret):
        print("未保存：输入为空或包含空白，请重新运行。")
        return
    # 先限制文件权限，再写入；真实密钥仅写入配置，不显示在终端。
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write("FUYAO_API_KEY=" + secret + "\n")
    print("已安全保存扶摇密钥。请回到聊天告诉我：已保存。")


if __name__ == "__main__":
    main()
