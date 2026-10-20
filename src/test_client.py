import sys, selectors, wwcomm
c = wwcomm.Client(); sel = selectors.DefaultSelector()
sel.register(c.sock, selectors.EVENT_READ, "net")
sel.register(sys.stdin, selectors.EVENT_READ, "kbd")
while True:
    for key, _ in sel.select():
        if key.data == "kbd":
            line = sys.stdin.readline()
            if not line: sys.exit()
            c.send({"type": "chat", "text": line.strip(), "from": "FAKE"})
        else:
            msgs = c.recv()
            if msgs is None: print("server closed"); sys.exit()
            for m in msgs: print(m)
