import wwcomm
srv = wwcomm.Server(); srv.start(); print("moderator up", flush=True)
while True:
    for kind, name, msg in srv.poll(1.0):
        print(kind, name, msg, flush=True)
        if kind == "join":    srv.broadcast({"type": "sys", "text": f"{name} joined"})
        elif kind == "leave": srv.broadcast({"type": "sys", "text": f"{name} left"})
        elif kind == "msg":   srv.broadcast({"type": "chat", "from": name, "text": str(msg.get("text", ""))[:200]})
