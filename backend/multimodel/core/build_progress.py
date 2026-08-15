"""索引构建进度跟踪（供前端轮询显示进度条）。

图像/音频各自的构建（watchdog / 防抖调度器）在 start/tick/finish 更新状态；
GET /build_progress/?kind= 返回当前状态。线程安全。
"""
import threading

_Kinds = ("image", "audio")


def _empty():
    return {
        "active": False,
        "phase": "idle",       # idle | collecting | extracting | building | done | error
        "current": 0,
        "total": 0,
        "index_name": "",
        "error": "",
    }


class BuildProgress:
    _slots = {k: _empty() for k in _Kinds}
    _lock = threading.Lock()

    @classmethod
    def start(cls, kind, index_name, total, phase="extracting"):
        with cls._lock:
            cls._slots[kind] = {
                "active": True,
                "phase": phase,
                "current": 0,
                "total": int(total),
                "index_name": index_name,
                "error": "",
            }

    @classmethod
    def tick(cls, kind, current):
        with cls._lock:
            s = cls._slots[kind]
            if s["active"]:
                s["current"] = int(current)

    @classmethod
    def set_phase(cls, kind, phase):
        with cls._lock:
            s = cls._slots[kind]
            if s["active"]:
                s["phase"] = phase

    @classmethod
    def finish(cls, kind, error=None):
        with cls._lock:
            cls._slots[kind] = {
                "active": False,
                "phase": "error" if error else "done",
                "current": cls._slots[kind]["total"],
                "total": cls._slots[kind]["total"],
                "index_name": cls._slots[kind]["index_name"],
                "error": str(error) if error else "",
            }

    @classmethod
    def get(cls, kind):
        with cls._lock:
            return dict(cls._slots.get(kind, _empty()))
