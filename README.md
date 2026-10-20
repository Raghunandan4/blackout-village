# Blackout Village

A Werewolf (Mafia) game for 7-8 players on one Linux machine, built on a
single-file communications library over a UNIX domain socket.

**Communications library: `src/wwcomm.py`** (installed to `/opt/blackout/wwcomm.py`).
**Socket: `/run/blackout/game.sock`**, mode 0660, owner `bv_mod`, group `bv_players`.

## Files

| File | Purpose |
|---|---|
| `src/wwcomm.py` | The communications library (single file, Python standard library only) |
| `src/moderator.py` | Game referee: roles, phases, timers, win conditions, logging |
| `src/client.py` | Terminal client each player runs as their own Linux user |
| `src/test_server.py`, `src/test_client.py` | Test scripts used for the robustness and security tests |
| `scripts/setup.sh` | Creates group `bv_players`, users `bv_mod`, `bv_p1`..`bv_p8`, and directories (run once, with sudo) |
| `scripts/deploy.sh` | Copies `src/*.py` to `/opt/blackout` and creates `/run/blackout` (run after every edit and after every reboot) |
| `scripts/teardown.sh` | Removes all users, the group and the directories |

## Requirements

Ubuntu/Debian Linux with sudo, and Python 3. The setup creates real Linux users,
so use a VM, not your main machine.

## Setup

    git clone https://github.com/Raghunandan4/blackout-village
    cd blackout-village
    sudo ./scripts/setup.sh
    ./scripts/deploy.sh

`/run` is a temporary filesystem, so run `./scripts/deploy.sh` again after a reboot.

## How to play

1. Open a terminal for the moderator and start it:

        sudo -u bv_mod python3 /opt/blackout/moderator.py

   Add `--fast` for short test timers. Type `start` at the moderator prompt once
   7-8 players have joined. `status` prints the phase and all roles (only on
   this terminal), and `quit` stops it.

2. Open one terminal per player (7 or 8) and run, using `bv_p1`..`bv_p8`:

        sudo -u bv_p1 python3 /opt/blackout/client.py

3. Roles: 2 wolves, 1 doctor, 1 seer, the rest villagers. Wolves win when they
   are as many as the villagers; villagers win when both wolves are dead.

## Round structure (normal timers)

| Phase | Time | Who acts |
|---|---|---|
| Wolves | 120s | Living wolves: `/wc <msg>` to discuss, `/kill <name>` to vote |
| Seer | 60s | Seer only: `/see <name>` (reply is instant) |
| Doctor | 60s | Doctor only: `/protect <name>` (each player can be protected once per game) |
| Day talk | 120s | Everyone alive: chat, `/w <name> <msg>` (2 whispers each), `/blackout` (once per player; turns public chat off until the vote) |
| Vote | 120s | Everyone alive: `/vote <name>` |

A phase ends early when everyone who can act has acted. A warning is sent
15 seconds before each phase ends. Other commands: `/status`, `/help`.

## Communications library API (`src/wwcomm.py`)

Transport: one AF_UNIX SOCK_STREAM socket. Messages are newline-delimited JSON
objects, at most 4096 bytes per line. The moderator reads each client's real
user id with `SO_PEERCRED`, so a client cannot fake who it is. The server runs
a single non-blocking event loop (selectors) with per-client buffers.

### `Server(path=SOCK_PATH, group="bv_players")`

| Method | Description |
|---|---|
| `start()` | Create the socket (mode 0660, group `bv_players`) and start listening |
| `poll(timeout=None)` | Run the event loop once; returns events of the form `(kind, name, msg)` where kind is `"join"`, `"leave"` or `"msg"` |
| `send(name, obj)` | Unicast a JSON-serializable object to one player |
| `multicast(names, obj)` | Send to a list of players (used for wolf chat) |
| `broadcast(obj, exclude=())` | Send to every connected player |
| `kick(name)` | Disconnect a player |

### `Client(path=SOCK_PATH)`

| Method | Description |
|---|---|
| `fileno()` | File descriptor, for select/poll loops |
| `send(obj)` | Send one JSON object to the moderator |
| `recv()` | Read and return decoded messages from the moderator |
| `close()` | Close the connection |

### Message types

Client to moderator: `chat`, `wolfchat`, `kill`, `see`, `protect`, `vote`,
`whisper` (with `to`), `blackout`, `status`.
Moderator to client: `sys`, `chat`, `wolfchat`, `whisper`, `role`, `error`.

## Security notes

- Only members of `bv_players` can connect (directory 0750, socket 0660).
- Identity comes from `SO_PEERCRED`, not from the message; the moderator
  overwrites any `from` field. One connection per username.
- Malformed JSON gets an error reply; lines over 4096 bytes drop the client.
- The moderator log is mode 0700/0600 and does not contain roles. An earlier
  version leaked all roles through a world-readable log (found and fixed).
- Known limitations: phase lengths and early endings leak timing information
  (for example that the seer is dead), and the moderator announces that a
  whisper was sent (not its content).
