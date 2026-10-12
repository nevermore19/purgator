#!/usr/bin/env bash
# Usage: scripts/setup.sh [--pip-qt]
set -euo pipefail

cd "$(dirname "$0")/.."

pip_qt=false
case "${1:-}" in
    --pip-qt) pip_qt=true ;;
    "") ;;
    *) echo "usage: $0 [--pip-qt]" >&2; exit 2 ;;
esac

have_system_pyside() {
    /usr/bin/python3 -c 'import PySide6.QtWidgets' 2>/dev/null
}

install_system_pyside() {
    . /etc/os-release
    case " $ID ${ID_LIKE:-} " in
        *" arch "*)
            sudo pacman -S --needed pyside6
            ;;
        *" debian "*)
            sudo apt-get install -y python3-venv
            # PySide6 is packaged since Debian 13
            sudo apt-get install -y python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
                || echo "!! PySide6 not available from apt" >&2
            ;;
        *)
            echo "!! Unsupported distro '$ID'" >&2
            ;;
    esac
}

if ! $pip_qt && ! have_system_pyside; then
    install_system_pyside
fi

if ! $pip_qt && have_system_pyside; then
    # Old venv without system packages would shadow system PySide6
    if [[ -f .venv/pyvenv.cfg ]] && ! grep -q '^include-system-site-packages = true' .venv/pyvenv.cfg; then
        echo ">> Recreating .venv with --system-site-packages"
        rm -rf .venv
    fi
    [[ -d .venv ]] || /usr/bin/python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -e .
else
    echo ">> Using PySide6 from PyPI (no native theme)"
    [[ -d .venv ]] || python3 -m venv .venv
    .venv/bin/pip install -e '.[qt]'
fi

.venv/bin/python -c 'import PySide6.QtCore as c; print(">> Ready: Qt", c.qVersion(), "from", c.__file__)'