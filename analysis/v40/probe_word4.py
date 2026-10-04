import sys, time
sys.path.insert(0, ".")
from doc_tool.application.word_check import check_word_available
for kwargs in ({"dispatch_timeout_seconds": 60.0}, {"dispatch_timeout_seconds": 30.0}):
    t0 = time.perf_counter()
    r = check_word_available(**kwargs)
    print(kwargs, "->", r.available, round(time.perf_counter() - t0, 1), "s | version:", getattr(r, "version", ""))