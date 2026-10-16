#!/bin/sh
# macOS resource summary; tmux refreshes this every five seconds.
LC_ALL=C
export LC_ALL
snapshot=$(/usr/bin/top -l 1 -n 0 2>/dev/null)
cpu=$(printf '%s\n' "$snapshot" | /usr/bin/awk '/CPU usage:/ {gsub(/%/, "", $3); gsub(/%/, "", $5); printf "%.0f%%", $3 + $5; exit}')
ram=$(printf '%s\n' "$snapshot" | /usr/bin/awk '/PhysMem:/ {printf "%s used", $2; exit}')
printf 'CPU %s | RAM %s' "${cpu:-N/A}" "${ram:-N/A}"
