@echo off
rem Closes the public Funnel address (the node keeps running locally).
tailscale funnel --https=443 off
tailscale funnel status
pause
