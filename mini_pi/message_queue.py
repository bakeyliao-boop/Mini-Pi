"""D13-C：串行追加输入队列；核心入队与取出逻辑由学习者手敲。"""

from collections import deque

from mini_pi.models import Message


# 在下方手敲 PendingMessageQueue；两种输入各自创建独立实例。
class PendingMessageQueue:
    def __init__(self):
        self._messages:deque[Message]=deque()

    def enqueue(self,text:str)->None:
        if not isinstance(text,str) or not text.strip():
            raise ValueError("追加输入必须是非空字符串")
        self._messages.append(Message("user",text))

    def drain_one(self)->list[Message]:
        if not self._messages:
            return []
        return [self._messages.popleft()]
