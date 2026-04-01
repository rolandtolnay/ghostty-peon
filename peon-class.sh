#!/usr/bin/env bash
# peon-class -- Select Warcraft III sound class for the current project.
#
# Usage:
#   peon-class              # Show current setting
#   peon-class orc          # Set to Orc sounds
#   peon-class human        # Set to Human sounds
#   peon-class nightelf     # Set to Night Elf sounds
#   peon-class undead       # Set to Undead sounds
#   peon-class random       # Random class per session (default)
#   peon-class none         # Disable sounds
#
# Source this file in your shell config:
#   source /path/to/ghostty-peon/peon-class.sh

peon-class() {
    local settings=".claude/settings.local.json"
    local valid="orc human nightelf undead random none"

    if [[ -z "$1" ]]; then
        # Show current setting
        if [[ -f "$settings" ]]; then
            local current
            current=$(python3 -c "
import json, sys
try:
    d = json.load(open('$settings'))
    print(d.get('env', {}).get('PEON_SOUND_CLASS', 'random'))
except: print('random')
")
            echo "$current"
        else
            echo "random (default)"
        fi
        return 0
    fi

    local cls
    cls=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    if [[ ! " $valid " == *" $cls "* ]]; then
        echo "Invalid class: $1"
        echo "Valid: orc, human, nightelf, undead, random, none"
        return 1
    fi

    python3 -c "
import json, os
path = '$settings'
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
data.setdefault('env', {})['PEON_SOUND_CLASS'] = '$cls'
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"
    echo "Peon sound class set to: $cls"
}
