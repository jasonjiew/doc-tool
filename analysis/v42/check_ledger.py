import io, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
text = io.open("docs/product-v40-v43-execution.md", encoding="utf-8").read()
print("total chars:", len(text))
print("42-E record present:", "42-E（5.1、5.2、5.4）" in text)
print("tail:")
print(text[-700:])