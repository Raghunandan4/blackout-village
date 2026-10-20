#!/bin/bash
sudo cp ~/cse536/project1/src/*.py /opt/blackout/
sudo chmod 755 /opt/blackout/*.py
sudo install -d -m 750 -o bv_mod -g bv_players /run/blackout
echo deployed
