#!/usr/bin/env bash
# peon-class -- Select Warcraft III sound class for the current project.
#
# Usage:
#   peon-class                         # Show Claude Code setting
#   peon-class orc                     # Set Claude Code sounds to Orc
#   peon-class --target claude human   # Set Claude Code sounds
#   peon-class --target pi undead      # Set Pi sounds
#   peon-class --target both random    # Set Claude Code + Pi sounds
#   peon-class --target all none       # Disable sounds for both runtimes
#
# Source this file in your shell config:
#   source /path/to/ghostty-peon/peon-class.sh

peon-class() {
    local target="claude"
    local cls=""
    local valid="orc human nightelf undead random none"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                if [[ -z "$2" ]]; then
                    echo "Missing value for --target"
                    return 1
                fi
                target=$(echo "$2" | tr '[:upper:]' '[:lower:]')
                shift 2
                ;;
            --target=*)
                target=$(echo "${1#--target=}" | tr '[:upper:]' '[:lower:]')
                shift
                ;;
            --help|-h)
                cat <<'EOF'
Usage:
  peon-class                         Show Claude Code setting
  peon-class orc                     Set Claude Code sounds to Orc
  peon-class --target claude human   Set Claude Code sounds
  peon-class --target pi undead      Set Pi sounds
  peon-class --target both random    Set Claude Code + Pi sounds
  peon-class --target all none       Disable sounds for both runtimes

Targets: claude, pi, both, all
Classes: orc, human, nightelf, undead, random, none
EOF
                return 0
                ;;
            *)
                if [[ -n "$cls" ]]; then
                    echo "Unexpected argument: $1"
                    return 1
                fi
                cls=$(echo "$1" | tr '[:upper:]' '[:lower:]')
                shift
                ;;
        esac
    done

    case "$target" in
        claude|pi|both|all) ;;
        *)
            echo "Invalid target: $target"
            echo "Valid targets: claude, pi, both, all"
            return 1
            ;;
    esac

    if [[ "$target" == "all" ]]; then
        target="both"
    fi

    _peon_class_settings_path() {
        case "$1" in
            claude) echo ".claude/settings.local.json" ;;
            pi) echo ".pi/settings.local.json" ;;
        esac
    }

    _peon_class_read() {
        local settings="$1"
        if [[ -f "$settings" ]]; then
            python3 - "$settings" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print(data.get('env', {}).get('PEON_SOUND_CLASS', 'random'))
except Exception:
    print('random')
PY
        else
            echo "random (default)"
        fi
    }

    _peon_class_write() {
        local settings="$1"
        local value="$2"
        python3 - "$settings" "$value" <<'PY'
import json, os, sys
path, value = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
if not isinstance(data.get('env'), dict):
    data['env'] = {}
data['env']['PEON_SOUND_CLASS'] = value
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PY
    }

    if [[ -z "$cls" ]]; then
        case "$target" in
            claude|pi)
                local settings
                settings=$(_peon_class_settings_path "$target")
                _peon_class_read "$settings"
                ;;
            both)
                local claude_settings pi_settings
                claude_settings=$(_peon_class_settings_path claude)
                pi_settings=$(_peon_class_settings_path pi)
                echo "claude: $(_peon_class_read "$claude_settings")"
                echo "pi: $(_peon_class_read "$pi_settings")"
                ;;
        esac
        unset -f _peon_class_settings_path _peon_class_read _peon_class_write
        return 0
    fi

    if [[ ! " $valid " == *" $cls "* ]]; then
        echo "Invalid class: $cls"
        echo "Valid: orc, human, nightelf, undead, random, none"
        unset -f _peon_class_settings_path _peon_class_read _peon_class_write
        return 1
    fi

    case "$target" in
        claude|pi)
            local settings
            settings=$(_peon_class_settings_path "$target")
            _peon_class_write "$settings" "$cls"
            echo "Peon sound class set for $target: $cls"
            ;;
        both)
            _peon_class_write "$(_peon_class_settings_path claude)" "$cls"
            _peon_class_write "$(_peon_class_settings_path pi)" "$cls"
            echo "Peon sound class set for claude + pi: $cls"
            ;;
    esac

    unset -f _peon_class_settings_path _peon_class_read _peon_class_write
}
