#!/bin/bash
[ "$EUID" -eq 0 ] || { echo "Run with sudo"; exit 1; }
for u in bv_mod bv_p1 bv_p2 bv_p3 bv_p4 bv_p5 bv_p6 bv_p7 bv_p8; do
    userdel -r "$u" 2>/dev/null
done
groupdel bv_players 2>/dev/null
rm -rf /opt/blackout /var/log/blackout /run/blackout
echo "Removed."
