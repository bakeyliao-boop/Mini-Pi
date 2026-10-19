"""助手准备：区分业务拒绝、版本冲突与不可信存储内容。"""


class MemoryPolicyError(ValueError):
    """来源、范围或片段不满足所选入库契约。"""


class MemoryConflict(RuntimeError):
    """同一来源被改写，或已有版本需由明确更新操作处理。"""


class MemoryDataError(ValueError):
    """已保存的数据无法安全还原；不静默跳过。"""


class MemoryContextError(RuntimeError):
    """预期的请求准备失败；接入时必须形成明确 error 终态。"""
