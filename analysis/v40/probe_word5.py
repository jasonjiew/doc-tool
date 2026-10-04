import sys, time
sys.path.insert(0, ".")
from doc_tool.application.word_check import check_word_available, _get_winword_pids
before = _get_winword_pids()
print("WINWORD before:", sorted(before))
results = []
for i in range(3):
    t0 = time.perf_counter()
    r = check_word_available()
    results.append((r.available, round(time.perf_counter() - t0, 1)))
after = _get_winword_pids()
print("probes:", results)
print("WINWORD after:", sorted(after), "| NEW (leaked):", sorted(after - before))
print("ALL TRUE:", all(x[0] for x in results))