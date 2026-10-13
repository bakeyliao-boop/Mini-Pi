"""D08：编辑工具；先实现唯一匹配，再加入受限路径与实际写入。"""


def find_unique_match(content: str, old_text: str) -> int:
    """返回旧文本唯一出现的位置；定位不明确时拒绝，不执行文件读写。"""
    if not old_text:
        raise ValueError("旧文本不能为空")

    index = content.find(old_text)
    if index == -1:
        raise ValueError("未找到代替换的旧文本")

    if content.find(old_text,index+1) != -1:
        raise ValueError("旧文本匹配多处，请提供更多上下文")

    return index


def replace_unique_text(content: str, old_text: str, new_text: str) -> str:
    """唯一匹配后返回替换后的文本；本函数不执行文件写入。"""
    index = find_unique_match(content,old_text)
    end = index + len(old_text)
    return content[:index] + new_text + content[end:]
