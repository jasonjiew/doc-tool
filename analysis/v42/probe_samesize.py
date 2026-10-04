import sys, os, tempfile, time
from pathlib import Path
sys.path.insert(0, ".")
from doc_tool.application.content import incremental_index as inc
from doc_tool.application.content.index import ContentIndexService

root = Path(tempfile.mkdtemp(prefix="probe-samesize-"))
content = root / "content" / "general"
content.mkdir(parents=True)
target = content / "1 章节.md"
target.write_text("# 原始标题AAA\n\n正文。\n", encoding="utf-8")
svc = ContentIndexService(content)
svc.build()  # 落缓存
before = svc.build().lines[str(target.relative_to(content).as_posix())]
st = target.stat()
# 同长度、同 mtime 改写
target.write_text("# 改写标题BBB\n\n正文。\n", encoding="utf-8")
os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
after_svc = ContentIndexService(content)
index = after_svc.build()
rel = str(target.relative_to(content).as_posix())
after = index.lines[rel]
print("size same:", target.stat().st_size == st.st_size, "mtime same:", target.stat().st_mtime_ns == st.st_mtime_ns)
print("before:", before[0])
print("after :", after[0])
print("detected:", after[0] != before[0], "parseCount", after_svc.stats()["parseCount"])
inc.reset_digest_cache()
svc2 = ContentIndexService(content)
idx2 = svc2.build()
print("without digest cache after:", idx2.lines[rel][0], "parseCount", svc2.stats()["parseCount"])