"""评测日志的 UTF-8 JSON 落盘辅助函数。"""

import json


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
