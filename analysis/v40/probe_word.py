import sys
sys.path.insert(0, ".")
try:
    from doc_tool.application.word_check import check_word_available
    r = check_word_available(dispatch_timeout_seconds=15)
    print("available:", r.available, "| detail:", (getattr(r, "detail", "") or getattr(r, "reason", ""))[:160])
except Exception as exc:
    print("probe error:", type(exc).__name__, str(exc)[:200])