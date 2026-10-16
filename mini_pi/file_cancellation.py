"""D12 文件操作的协作取消；只负责请求与检查，不负责等待线程。

每次调用单独创建，异步等待方与同步文件操作持有同一个对象。
取消登记与写入许可共用一个短锁；锁内不执行任何文件 I/O。
begin_write 检查通过即准许本次写入，之后的取消不能撤回许可；
调用方仍须等待已获准的工作结束，不能据此提前报告收尾。
"""

from threading import Event, Lock


class FileOperationCancelled(Exception):
    """文件操作在检查点观察到取消；不表示文件一定没有改变。"""


class FileCancellation:
    """助手准备：封装线程安全的取消标记和写入许可检查。"""

    def __init__(self):
        self._requested = Event()
        self._decision_lock = Lock()

    def request_cancel(self) -> None:
        """等待方登记取消请求；与写入许可判定互斥。"""
        with self._decision_lock:
            self._requested.set()

    def check(self) -> None:
        """未取消时正常经过；已取消时抛出专用异常。"""
        if self._requested.is_set():
            raise FileOperationCancelled("文件操作已取消")

    def begin_write(self) -> None:
        """检查通过即准许一次写入；返回后发生的取消按在途工作收尾。"""
        with self._decision_lock:
            self.check()
