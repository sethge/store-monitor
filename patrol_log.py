"""巡检日志模块 — 每个关键步骤都记，debug时一目了然"""
import json, os, time
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(__file__), "ops-logger", "patrol_debug.json")
_entries = []
_start_ts = None


def start():
    """开始新一轮巡检，清空旧日志"""
    global _entries, _start_ts
    _entries = []
    _start_ts = time.time()
    _write()


def step(phase, msg, ok=True, detail=None):
    """记录一步"""
    entry = {
        "t": datetime.now().strftime("%H:%M:%S"),
        "elapsed": f"{time.time() - _start_ts:.1f}s" if _start_ts else "",
        "phase": phase,
        "msg": msg,
        "ok": ok,
    }
    if detail is not None:
        entry["detail"] = str(detail)[:500]
    _entries.append(entry)
    # 同时打印
    icon = "✓" if ok else "✗"
    print(f"  [{entry['t']}] {icon} [{phase}] {msg}", flush=True)
    # 每步都写文件，方便实时看
    _write()


def error(phase, msg, detail=None):
    """记录错误"""
    step(phase, msg, ok=False, detail=detail)


def _write():
    """写到JSON文件"""
    try:
        data = {
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(_entries),
            "errors": sum(1 for e in _entries if not e["ok"]),
            "log": _entries[-200:],  # 最近200条
        }
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def summary():
    """返回摘要字符串"""
    total = len(_entries)
    errors = sum(1 for e in _entries if not e["ok"])
    elapsed = f"{time.time() - _start_ts:.0f}s" if _start_ts else "?"
    return f"{total}步 {errors}错误 {elapsed}"
