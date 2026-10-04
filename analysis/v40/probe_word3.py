import sys, time
sys.path.insert(0, ".")
from doc_tool.application.word_check import check_word_available

# 同一会话内连续 3 次探测：修复后必须都为 True（默认预算 10s 也要能覆盖冷启动）
results = []
for i in range(3):
    t0 = time.perf_counter()
    r = check_word_available()          # 默认参数（生产代码走的就是这条）
    results.append((r.available, round(time.perf_counter() - t0, 1)))
print("default-arg probes:", results)
avail = [item[0] for item in results]
print("ALL TRUE:", all(avail), "| any true:", any(avail))