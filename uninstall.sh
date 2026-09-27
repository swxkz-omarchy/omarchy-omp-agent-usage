#!/usr/bin/env bash
# Remove the Oh My Pi usage collector, its timer, and the record it wrote.

set -euo pipefail

collector="$HOME/.local/bin/omarchy-agent-usage-omp"
unit_dir="$HOME/.config/systemd/user"
record="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage/omp.json"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/agent-usage/omp-sessions.json"

if systemctl --user is-active --quiet omp-agent-usage.timer; then
  systemctl --user disable --now omp-agent-usage.timer
fi
rm -f "$unit_dir/omp-agent-usage.timer" "$unit_dir/omp-agent-usage.service"
systemctl --user daemon-reload

rm -f "$collector" "$record" "$cache" "$cache.lock"

# The panel rediscovers its records whenever a refresh finishes, so the chip
# disappears on its own; nothing else needs restarting.
echo "removed collector, timer, record, and scan cache"
