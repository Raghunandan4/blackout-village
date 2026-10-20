#!/bin/bash
set -e
[ "$EUID" -eq 0 ] || { echo "Run with sudo"; exit 1; }

groupadd -f bv_players

id bv_mod &>/dev/null || useradd -m -s /bin/bash bv_mod
usermod -aG bv_players bv_mod

for i in 1 2 3 4 5 6 7 8; do
    id bv_p$i &>/dev/null || useradd -m -s /bin/bash bv_p$i
    usermod -aG bv_players bv_p$i
done

install -d -m 755 /opt/blackout
install -d -m 700 -o bv_mod -g bv_mod /var/log/blackout
echo "Setup done:"
id bv_mod; id bv_p1
