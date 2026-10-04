import base64, sys, pathlib
target = pathlib.Path(sys.argv[1])
data = base64.b64decode(sys.stdin.read())
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(data)
print("wrote", target, len(data))
