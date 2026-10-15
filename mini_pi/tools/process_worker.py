"""助手准备：先等父进程完成管理绑定，再启动固定命令；无模型参数。"""

import json
from pathlib import Path
import subprocess
import sys


def main():
    metadata = Path(sys.argv[1])
    command = sys.argv[2:]
    # 未绑定 Job / 进程组之前，父进程不会发送启动许可。
    if sys.stdin.buffer.read(1) != b"\n":
        return 125
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    except OSError as error:
        metadata.write_text(json.dumps({"execution_error": str(error)}), encoding="utf-8")
        return 127
    metadata.write_text(json.dumps({"pid": process.pid}), encoding="utf-8")
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
