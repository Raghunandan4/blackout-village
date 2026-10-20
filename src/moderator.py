#!/usr/bin/env python3
"""moderator.py - Blackout Village referee. Run as user bv_mod."""
import argparse, random, select, sys, time
import wwcomm

MIN_P, MAX_P, WHISPERS = 7, 8, 2
NIGHT_PHASES = ("NIGHT_WOLF", "NIGHT_SEER", "NIGHT_DOC")


def top_voted(votes):
    c = {}
    for t in votes.values():
        c[t] = c.get(t, 0) + 1
    if not c:
        return []
    m = max(c.values())
    return [k for k, n in c.items() if n == m]


class Game:
    def __init__(self, srv, timers):
        self.srv, self.t = srv, timers
        try:
            self.logf = open("/var/log/blackout/moderator.log", "a")
        except OSError:
            self.logf = None
        self.reset()

    def reset(self):
        self.phase, self.deadline = "LOBBY", None
        self.players, self.role, self.alive = [], {}, set()
        self.round, self.wolfvotes, self.votes = 0, {}, {}
        self.victim, self.seer_done = None, False
        self.doc_target, self.doc_used = None, set()
        self.blackout, self.bo_used, self.whispers = False, set(), {}
        self.warn_key = None

    def log(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        if self.logf:
            self.logf.write(line + "\n"); self.logf.flush()

    def pub(self, text):                       # broadcast (dead players included)
        self.srv.broadcast({"type": "sys", "text": text})

    def to(self, name, text, typ="sys"):       # unicast
        self.srv.send(name, {"type": typ, "text": text})

    def living(self, role):
        return sorted(n for n in self.alive if self.role[n] == role)

    def one(self, role):
        l = self.living(role)
        return l[0] if l else None

    def alive_text(self):
        return ", ".join(sorted(self.alive))

    def doc_options(self):
        return sorted(self.alive - self.doc_used)

    def set_phase(self, phase, secs):
        self.phase, self.deadline = phase, time.time() + secs

    # ---- connections ----
    def on_join(self, name):
        if self.phase != "LOBBY" or len(self.players) >= MAX_P:
            self.to(name, "Game in progress or full. Reconnect later.", "error")
            self.srv.kick(name)
            return
        self.players.append(name)
        self.log("JOIN %s (%d/%d)" % (name, len(self.players), MAX_P))
        self.pub("%s joined the lobby (%d/%d)." % (name, len(self.players), MAX_P))
        self.to(name, "Welcome %s. The moderator starts the game once %d+ players are in. Type /help." % (name, MIN_P))

    def on_leave(self, name):
        if name not in self.players:
            return
        if self.phase == "LOBBY":
            self.players.remove(name)
            self.pub("%s left the lobby." % name)
        elif name in self.alive and self.phase != "END":
            self.kill(name, "fled the village")

    # ---- game flow ----
    def start(self):
        n = len(self.players)
        if self.phase != "LOBBY" or n < MIN_P:
            print("Cannot start (phase=%s, players=%d, need %d-%d)" % (self.phase, n, MIN_P, MAX_P)); return
        roles = ["wolf", "wolf", "doctor", "seer"] + ["villager"] * (n - 4)
        random.shuffle(roles)
        self.role = dict(zip(self.players, roles))
        self.alive = set(self.players)
        self.whispers = {p: WHISPERS for p in self.players}
        self.log("START with %d players" % n)
        ws = ", ".join(self.living("wolf"))
        msg = {"wolf": "You are a WEREWOLF. Your pack: %s." % ws,
               "doctor": "You are the DOCTOR. Each night /protect <name> (yourself too). You can protect each player only once per game.",
               "seer": "You are the SEER. Each night /see <name> to learn if someone is a werewolf.",
               "villager": "You are a VILLAGER. Find the werewolves and hang them."}
        for p in self.players:
            self.to(p, msg[self.role[p]], "role")
        self.pub("The game begins: %d players = 2 wolves, 1 doctor, 1 seer, %d villagers." % (n, n - 4))
        self.begin_night()

    # night 1/3: wolves
    def begin_night(self):
        self.round += 1
        self.wolfvotes, self.victim = {}, None
        self.seer_done, self.doc_target = False, None
        self.blackout = False
        self.pub("=== NIGHT %d === The village sleeps. Alive: %s" % (self.round, self.alive_text()))
        self.set_phase("NIGHT_WOLF", self.t["wolf"])
        self.pub("The wolves wake (%ds)." % self.t["wolf"])
        prey = ", ".join(sorted(self.alive - set(self.living("wolf"))))
        for w in self.living("wolf"):
            self.to(w, "Wolves (%ds): /wc <msg> to discuss, /kill <name> to vote. Prey: %s" % (self.t["wolf"], prey))

    def end_wolves(self):
        top = top_voted({v: t for v, t in self.wolfvotes.items() if v in self.alive})
        self.victim = random.choice(top) if top else None
        for w in self.living("wolf"):
            self.to(w, "The pack's target: %s." % (self.victim or "nobody"))
        self.log("WOLVES target %s" % self.victim)
        self.pub("The wolves go back to sleep.")
        self.begin_seer()

    # night 2/3: seer
    def begin_seer(self):
        s = self.one("seer")
        if not s:
            return self.begin_doctor()
        self.set_phase("NIGHT_SEER", self.t["seer"])
        self.pub("The seer wakes (%ds)." % self.t["seer"])
        self.to(s, "Seer (%ds): /see <name> to inspect someone." % self.t["seer"])

    def end_seer(self):
        self.pub("The seer goes back to sleep.")
        self.begin_doctor()

    # night 3/3: doctor
    def begin_doctor(self):
        d, opts = self.one("doctor"), self.doc_options()
        if not d:
            return self.dawn()
        if not opts:
            self.to(d, "You have already protected everyone alive.")
            return self.dawn()
        self.set_phase("NIGHT_DOC", self.t["doc"])
        self.pub("The doctor wakes (%ds)." % self.t["doc"])
        self.to(d, "Doctor (%ds): /protect <name>. Not yet protected: %s" % (self.t["doc"], ", ".join(opts)))

    def end_doctor(self):
        self.pub("The doctor goes back to sleep.")
        self.dawn()

    def dawn(self):
        self.pub("=== DAWN %d ===" % self.round)
        v = self.victim
        if v and v in self.alive and v == self.doc_target:
            self.pub("The wolves attacked, but the Doctor saved their target! Nobody died.")
            self.log("SAVE doctor saved %s" % v)
        elif v and v in self.alive:
            if self.kill(v, "was eaten by the wolves"):
                return
        else:
            self.pub("A quiet night. Nobody died.")
        self.set_phase("DAY_TALK", self.t["talk"])
        self.pub("DAY TALK (%ds). Alive: %s. Chat freely, /w <name> <msg> (%d whispers each), /blackout (once per player)." % (self.t["talk"], self.alive_text(), WHISPERS))

    def begin_vote(self):
        self.set_phase("DAY_VOTE", self.t["vote"])
        self.votes, self.blackout = {}, False
        self.pub("VOTE (%ds): /vote <name> to hang someone. Alive: %s" % (self.t["vote"], self.alive_text()))

    def end_vote(self):
        top = top_voted({v: t for v, t in self.votes.items() if v in self.alive})
        if len(top) == 1:
            if self.kill(top[0], "was hanged by the town"):
                return
        else:
            self.pub("Tie or no votes. Nobody is hanged.")
        self.begin_night()

    def kill(self, name, how):
        self.alive.discard(name)
        self.pub("%s %s. They were a %s." % (name, how, self.role[name].upper()))
        self.to(name, "You are dead. You can still watch, but not act.")
        self.log("DEATH %s (%s): %s" % (name, self.role[name], how))
        return self.check_win()

    def check_win(self):
        w = len(self.living("wolf"))
        if w == 0:
            self.finish("VILLAGERS WIN")
        elif w >= len(self.alive) - w:
            self.finish("WOLVES WIN")
        else:
            return False
        return True

    def finish(self, result):
        self.pub("*** %s ***" % result)
        self.pub("Roles: " + ", ".join("%s=%s" % (p, self.role[p]) for p in self.players))
        self.log(result)
        self.set_phase("END", 5)

    # ---- timers ----
    def warn(self, now):
        dur = {"NIGHT_WOLF": self.t["wolf"], "NIGHT_SEER": self.t["seer"], "NIGHT_DOC": self.t["doc"],
               "DAY_TALK": self.t["talk"], "DAY_VOTE": self.t["vote"]}.get(self.phase)
        if dur is None or self.deadline is None:
            return
        left = self.deadline - now
        key = (self.phase, self.round)
        if left > min(15, dur // 2) or left <= 0 or self.warn_key == key:
            return
        self.warn_key = key
        sec = int(left) + 1
        if self.phase == "NIGHT_WOLF":
            for w in self.living("wolf"):
                if w not in self.wolfvotes:
                    self.to(w, "%ds left! /kill <name> to vote." % sec)
        elif self.phase == "NIGHT_SEER" and self.one("seer") and not self.seer_done:
            self.to(self.one("seer"), "%ds left! /see <name> to inspect someone." % sec)
        elif self.phase == "NIGHT_DOC" and self.one("doctor") and self.doc_target is None:
            self.to(self.one("doctor"), "%ds left! /protect <name> to save someone." % sec)
        elif self.phase == "DAY_TALK":
            self.pub("%ds left of discussion. Voting starts next." % sec)
        elif self.phase == "DAY_VOTE":
            for a in sorted(self.alive):
                if a not in self.votes:
                    self.to(a, "%ds left! /vote <name> to hang someone." % sec)

    def tick(self):
        now = time.time()
        self.warn(now)
        late = self.deadline is not None and now >= self.deadline
        if self.phase == "NIGHT_WOLF":
            if late or all(w in self.wolfvotes for w in self.living("wolf")):
                self.end_wolves()
        elif self.phase == "NIGHT_SEER":
            if late or self.seer_done or not self.one("seer"):
                self.end_seer()
        elif self.phase == "NIGHT_DOC":
            if late or self.doc_target is not None or not self.one("doctor"):
                self.end_doctor()
        elif self.phase == "DAY_TALK" and late:
            self.begin_vote()
        elif self.phase == "DAY_VOTE":
            if late or all(a in self.votes for a in self.alive):
                self.end_vote()
        elif self.phase == "END" and late:
            old = self.players
            self.reset()
            for p in old:
                self.srv.send(p, {"type": "sys", "text": "Game over. Reconnect to play again."})
                self.srv.kick(p)
            self.log("RESET to lobby")

    # ---- player messages ----
    def handle(self, name, msg):
        if name not in self.players:
            return
        typ = str(msg.get("type", ""))
        text = str(msg.get("text", ""))[:200].strip()
        target = str(msg.get("target", "")).strip()
        alive = name in self.alive
        day = self.phase in ("DAY_TALK", "DAY_VOTE")
        role = self.role.get(name)
        err = lambda t: self.to(name, t, "error")

        if typ == "chat":
            if not text: return
            if self.phase == "LOBBY":
                self.srv.broadcast({"type": "chat", "from": name, "text": text})
            elif not alive: err("Dead players cannot talk.")
            elif not day: err("Everyone is asleep.")
            elif self.blackout: err("BLACKOUT: public chat is off. Use /w.")
            else: self.srv.broadcast({"type": "chat", "from": name, "text": text})
        elif typ == "wolfchat":
            if self.phase == "NIGHT_WOLF" and alive and role == "wolf" and text:
                self.srv.multicast(self.living("wolf"), {"type": "wolfchat", "from": name, "text": text})
            else: err("Wolf chat is only for living wolves during their turn.")
        elif typ == "kill":
            if not (self.phase == "NIGHT_WOLF" and alive and role == "wolf"): return err("It is not your turn.")
            if target not in self.alive or self.role[target] == "wolf": return err("Invalid victim.")
            self.wolfvotes[name] = target
            self.srv.multicast(self.living("wolf"), {"type": "sys", "text": "%s votes to eat %s." % (name, target)})
        elif typ == "see":
            if not (self.phase == "NIGHT_SEER" and alive and role == "seer"): return err("It is not your turn.")
            if self.seer_done: return err("You already looked tonight.")
            if target not in self.alive or target == name: return err("Invalid target.")
            self.seer_done = True
            self.to(name, "Vision: %s is %s." % (target, "a WEREWOLF" if self.role[target] == "wolf" else "NOT a werewolf"))
            self.log("SEER %s inspected %s" % (name, target))
        elif typ == "protect":
            if not (self.phase == "NIGHT_DOC" and alive and role == "doctor"): return err("It is not your turn.")
            if self.doc_target is not None: return err("You already chose tonight.")
            if target not in self.alive: return err("Invalid target.")
            if target in self.doc_used: return err("You already protected %s once." % target)
            self.doc_target = target
            self.doc_used.add(target)
            self.to(name, "You will protect %s tonight." % target)
            self.log("DOCTOR %s protects %s" % (name, target))
        elif typ == "vote":
            if not (self.phase == "DAY_VOTE" and alive): return err("You cannot vote now.")
            if target not in self.alive or target == name: return err("Invalid target.")
            self.votes[name] = target
            self.pub("%s voted for %s." % (name, target))
        elif typ == "whisper":
            to = str(msg.get("to", "")).strip()
            if not (self.phase == "DAY_TALK" and alive): return err("You can only whisper during day talk.")
            if to not in self.alive or to == name or not text: return err("Bad whisper.")
            if self.whispers[name] <= 0: return err("No whispers left.")
            self.whispers[name] -= 1
            self.srv.send(to, {"type": "whisper", "from": name, "text": text})
            self.srv.send(name, {"type": "whisper", "from": "you->" + to, "text": text})
            self.pub("%s sent a private whisper." % name)
            self.log("WHISPER %s -> %s: %s" % (name, to, text))
        elif typ == "blackout":
            if not (self.phase == "DAY_TALK" and alive): return err("You can only do that during day talk.")
            if name in self.bo_used: return err("You already used your blackout.")
            if self.blackout: return err("Already dark.")
            self.bo_used.add(name); self.blackout = True
            self.pub("BLACKOUT! Public chat is off until the vote. Whispers still work.")
            self.log("BLACKOUT by %s" % name)
        elif typ == "status":
            self.to(name, "Phase=%s round=%d role=%s alive=[%s] whispers_left=%d" % (
                self.phase, self.round, role or "?", self.alive_text(), self.whispers.get(name, 0)))
        else:
            err("Unknown command.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="short timers for testing")
    a = ap.parse_args()
    if a.fast:
        timers = dict(wolf=20, seer=10, doc=10, talk=20, vote=12)
    else:
        timers = dict(wolf=120, seer=60, doc=60, talk=120, vote=120)
    srv = wwcomm.Server(); srv.start()
    g = Game(srv, timers)
    print("Moderator ready. Commands: start | status | quit", flush=True)
    stdin_open = True
    try:
        while True:
            for kind, name, msg in srv.poll(0.2):
                try:
                    if kind == "join": g.on_join(name)
                    elif kind == "leave": g.on_leave(name)
                    elif kind == "msg": g.handle(name, msg)
                except Exception as e:
                    g.log("ERROR handling %s from %s: %r" % (kind, name, e))
            if stdin_open and select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if line == "": stdin_open = False
                else:
                    cmd = line.strip()
                    if cmd == "start": g.start()
                    elif cmd == "status": print(g.phase, g.players, g.role, sorted(g.alive))
                    elif cmd == "quit": break
            try:
                g.tick()
            except Exception as e:
                g.log("ERROR tick: %r" % e)
    except KeyboardInterrupt:
        pass
    srv.broadcast({"type": "sys", "text": "Moderator shut down."})


if __name__ == "__main__":
    main()
