import sys, inspect, time
sys.path.insert(0, ".")
from doc_tool.application.word_check import check_word_available
print("signature:", inspect.signature(check_word_available))
for kwargs in ({}, {"dispatch_check": True}, {"dispatch_timeout_seconds": 15},
               {"dispatch_check": True, "dispatch_timeout_seconds": 60.0},
               {"dispatch_check": True, "dispatch_timeout_seconds": 15}):
    t0 = time.perf_counter()
    try:
        r = check_word_available(**kwargs)
        info = (r.available, getattr(r, "detail", "") or getattr(r, "reason", "") or
                getattr(r, "message", ""))
    except Exception as exc:
        info = ("ERROR", "{0}: {1}".format(type(exc).__name__, exc))
    print("{0:<58} -> {1}  ({2:.1f}s)".format(str(kwargs), str(info)[:90], time.perf_counter()-t0))