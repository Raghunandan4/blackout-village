"""wwcomm.py - single-file comms library for Blackout Village (v0).
UNIX stream socket + epoll (selectors) + SO_PEERCRED identity. Newline-delimited JSON."""
import os, json, socket, struct, pwd, grp, selectors

SOCK_PATH = "/run/blackout/game.sock"
SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)   # Linux value
MAX_LINE = 4096          # max bytes per message
MAX_OUTBUF = 1 << 20     # drop clients that never read

def _enc(obj):
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()

class _Conn:
    def __init__(self, sock, name, uid, pid):
        self.sock, self.name, self.uid, self.pid = sock, name, uid, pid
        self.rbuf, self.wbuf, self.dead = b"", b"", False

class Server:
    def __init__(self, path=SOCK_PATH, group="bv_players"):
        self.path, self.group = path, group
        self.sel = selectors.DefaultSelector()
        self.byname = {}
        self.leaves = []

    def start(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        ls = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ls.bind(self.path)
        os.chown(self.path, -1, grp.getgrnam(self.group).gr_gid)
        os.chmod(self.path, 0o660)
        ls.listen(16)
        ls.setblocking(False)
        self.ls = ls
        self.sel.register(ls, selectors.EVENT_READ, None)

    def poll(self, timeout=None):
        """Returns list of ('join'|'msg'|'leave', player_name, dict_or_None)."""
        events = []
        for key, mask in self.sel.select(timeout):
            if key.fileobj is self.ls:
                self._accept(events)
                continue
            c = key.data
            if c.dead:
                continue
            if mask & selectors.EVENT_READ:
                self._read(c, events)
            if mask & selectors.EVENT_WRITE and not c.dead:
                self._flush(c)
        events += self.leaves
        self.leaves = []
        return events

    def _accept(self, events):
        try:
            s, _ = self.ls.accept()
        except BlockingIOError:
            return
        s.setblocking(False)
        pid, uid, gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i")))
        name = pwd.getpwuid(uid).pw_name
        if name in self.byname:
            try: s.send(_enc({"type": "error", "text": "already connected"}))
            except OSError: pass
            s.close()
            return
        c = _Conn(s, name, uid, pid)
        self.byname[name] = c
        self.sel.register(s, selectors.EVENT_READ, c)
        events.append(("join", name, None))

    def _read(self, c, events):
        try:
            data = c.sock.recv(4096)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            return self._drop(c)
        c.rbuf += data
        while b"\n" in c.rbuf:
            line, _, c.rbuf = c.rbuf.partition(b"\n")
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict): raise ValueError
            except ValueError:
                self.send(c.name, {"type": "error", "text": "bad message"})
                continue
            events.append(("msg", c.name, obj))
        if len(c.rbuf) > MAX_LINE:
            self._drop(c)

    def _flush(self, c):
        if c.dead: return
        try:
            n = c.sock.send(c.wbuf) if c.wbuf else 0
        except BlockingIOError:
            n = 0
        except OSError:
            return self._drop(c)
        c.wbuf = c.wbuf[n:]
        if len(c.wbuf) > MAX_OUTBUF:
            return self._drop(c)
        ev = selectors.EVENT_READ | (selectors.EVENT_WRITE if c.wbuf else 0)
        self.sel.modify(c.sock, ev, c)

    def _drop(self, c):
        if c.dead: return
        c.dead = True
        try: self.sel.unregister(c.sock)
        except (KeyError, ValueError): pass
        c.sock.close()
        self.byname.pop(c.name, None)
        self.leaves.append(("leave", c.name, None))

    def send(self, name, obj):                  # unicast
        c = self.byname.get(name)
        if c and not c.dead:
            c.wbuf += _enc(obj)
            self._flush(c)

    def kick(self, name):
        c = self.byname.get(name)
        if c:
            self._drop(c)

    def multicast(self, names, obj):            # to a group
        for n in list(names):
            self.send(n, obj)

    def broadcast(self, obj, exclude=()):       # to everyone
        for n in list(self.byname):
            if n not in exclude:
                self.send(n, obj)

class Client:
    def __init__(self, path=SOCK_PATH):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.sock.setblocking(False)
        self.rbuf = b""

    def fileno(self):
        return self.sock.fileno()

    def send(self, obj):
        self.sock.setblocking(True)
        self.sock.sendall(_enc(obj))
        self.sock.setblocking(False)

    def recv(self):
        """List of dicts (maybe empty), or None if server closed."""
        try:
            data = self.sock.recv(4096)
        except BlockingIOError:
            return []
        except OSError:
            return None
        if not data:
            return None
        self.rbuf += data
        out = []
        while b"\n" in self.rbuf:
            line, _, self.rbuf = self.rbuf.partition(b"\n")
            try: out.append(json.loads(line))
            except ValueError: pass
        return out

    def close(self):
        self.sock.close()
