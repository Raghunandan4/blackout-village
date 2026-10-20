#!/usr/bin/env python3
"""client.py - Blackout Village player UI."""
import sys, selectors
import wwcomm

HELP = """Commands:
  <text>            public chat (day only)
  /wc <text>        wolf chat (wolves, night)
  /kill <name>      wolves: vote on a victim (night)
  /see <name>       seer: inspect a player (night)
  /protect <name>   doctor: protect a player (night; each player once, self allowed)
  /vote <name>      vote to hang someone (vote phase)
  /w <name> <text>  private whisper (2 per game, day talk)
  /blackout         mute public chat for the day talk (once per player)
  /status           show your state
  /quit             leave"""

SIMPLE = {"kill": "kill", "see": "see", "protect": "protect", "vote": "vote"}


def show(m):
    t, txt = m.get("type"), str(m.get("text", ""))
    if t == "chat": print("[%s] %s" % (m.get("from"), txt))
    elif t == "wolfchat": print("[WOLVES] %s: %s" % (m.get("from"), txt))
    elif t == "whisper": print("[WHISPER %s] %s" % (m.get("from"), txt))
    elif t == "role": print("\n######## %s ########\n" % txt)
    elif t == "error": print("!! %s" % txt)
    else: print("* %s" % txt)


def parse(line):
    line = line.strip()
    if not line: return None
    if not line.startswith("/"): return {"type": "chat", "text": line}
    parts = line[1:].split(None, 2)
    cmd = parts[0].lower() if parts else ""
    if cmd == "wc" and len(parts) > 1: return {"type": "wolfchat", "text": line[4:].strip()}
    if cmd in ("save",): cmd = "protect"
    if cmd in SIMPLE and len(parts) == 2: return {"type": SIMPLE[cmd], "target": parts[1]}
    if cmd == "w" and len(parts) == 3: return {"type": "whisper", "to": parts[1], "text": parts[2]}
    if cmd in ("blackout", "status"): return {"type": cmd}
    if cmd == "quit": return "quit"
    print(HELP)
    return None


def main():
    try:
        c = wwcomm.Client()
    except (FileNotFoundError, PermissionError, ConnectionRefusedError) as e:
        sys.exit("Cannot connect to moderator: %s" % e)
    sel = selectors.DefaultSelector()
    sel.register(c.sock, selectors.EVENT_READ, "net")
    sel.register(sys.stdin, selectors.EVENT_READ, "kbd")
    try:
        while True:
            for key, _ in sel.select():
                if key.data == "kbd":
                    line = sys.stdin.readline()
                    if not line: return
                    m = parse(line)
                    if m == "quit": return
                    if m: c.send(m)
                else:
                    msgs = c.recv()
                    if msgs is None:
                        print("-- disconnected from moderator --"); return
                    for m in msgs: show(m)
    except KeyboardInterrupt:
        pass
    finally:
        c.close()


if __name__ == "__main__":
    main()
