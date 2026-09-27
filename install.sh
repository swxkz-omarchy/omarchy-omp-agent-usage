#!/usr/bin/env bash
# Install the Oh My Pi usage collector and its refresh timer.
#
# Idempotent: rerunning it overwrites the same three files and re-enables the
# same timer. It never touches omarchy's own plugins or binaries.

set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
collector="$HOME/.local/bin/omarchy-agent-usage-omp"
unit_dir="$HOME/.config/systemd/user"
service="$unit_dir/omp-agent-usage.service"
timer="$unit_dir/omp-agent-usage.timer"
refresh_seconds="${OMP_USAGE_REFRESH_SECONDS:-300}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "install.sh: $1 is required but not on PATH" >&2
    exit 1
  }
}

need python3
need systemctl

if [[ ! -d "$HOME/.omp/agent/sessions" ]] && [[ -z "${PI_CODING_AGENT_SESSION_DIR:-}" ]]; then
  echo "install.sh: no ~/.omp/agent/sessions found - run 'omp' once, or set PI_CODING_AGENT_DIR" >&2
  exit 1
fi

mkdir -p "$(dirname -- "$collector")" "$unit_dir"
install -m 0755 "$source_dir/omarchy-agent-usage-omp" "$collector"

# The timer ships at 5 minutes; -D rewrites only the interval so an edited
# copy in this repo does not have to keep the unit file in sync by hand.
sed "s/^OnUnitActiveSec=.*/OnUnitActiveSec=${refresh_seconds}s/" \
  "$source_dir/systemd/omp-agent-usage.timer" >"$timer"
install -m 0644 "$source_dir/systemd/omp-agent-usage.service" "$service"

systemctl --user daemon-reload
# enable --now leaves an already-active timer untouched, so an edited
# schedule would keep running the old one. Restart to make the unit just
# written the unit in force.
systemctl --user enable --now omp-agent-usage.timer
systemctl --user restart omp-agent-usage.timer

# One run now, so the agents panel has a record before the first tick and the
# install proves the collector works on this machine.
"$collector" >/dev/null

echo "installed:"
echo "  $collector"
echo "  $service"
echo "  $timer (every ${refresh_seconds}s)"
echo
echo "check: systemctl --user list-timers omp-agent-usage.timer"
echo "open:  omarchy-shell omarchy.agents open"
