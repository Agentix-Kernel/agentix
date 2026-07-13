#!/usr/bin/env bash
# Agentix one-line installer — zero prior setup required.
#
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/euroblaze/agentix/main/scripts/install.sh | bash
#   curl -LsSf https://raw.githubusercontent.com/euroblaze/agentix/main/scripts/install.sh | AGENTIX_EXTRAS=anthropic,openai bash
#   curl -LsSf https://raw.githubusercontent.com/euroblaze/agentix/main/scripts/install.sh | AGENTIX_HOME=~/myproject bash
#
# Environment variables:
#   AGENTIX_HOME    — install root (default: ~/.agentix)
#   AGENTIX_EXTRAS  — comma-separated extras: anthropic,openai,groq,minio,hf,postgresql,all
#   AGENTIX_VERSION — pinned version (default: latest)

set -euo pipefail

AGENTIX_HOME="${AGENTIX_HOME:-$HOME/.agentix}"
AGENTIX_EXTRAS="${AGENTIX_EXTRAS:-}"
AGENTIX_VERSION="${AGENTIX_VERSION:-}"
VENV="$AGENTIX_HOME/venv"

# ── parse positional extras (bash install.sh anthropic openai) ──────────────
if [[ $# -gt 0 && -z "$AGENTIX_EXTRAS" ]]; then
    AGENTIX_EXTRAS=$(IFS=,; echo "$*")
fi

# ── OS check ─────────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Linux|Darwin) ;;
    *) echo "Agentix installer: unsupported OS '$OS'. Use Linux or macOS." >&2; exit 1 ;;
esac

# ── Python 3.12+ ──────────────────────────────────────────────────────────────
ensure_python() {
    for candidate in python3.12 python3.13 python3; do
        if command -v "$candidate" &>/dev/null; then
            ver=$("$candidate" -c 'import sys; print(sys.version_info[:2])')
            if [[ "$ver" > "(3, 11)" ]]; then
                PYTHON="$candidate"
                return
            fi
        fi
    done

    echo "Python 3.12+ not found — installing..."
    if [[ "$OS" == "Linux" ]]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y python3.12 python3.12-venv
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3.12
        else
            echo "Cannot auto-install Python on this Linux distro. Install Python 3.12+ manually." >&2
            exit 1
        fi
    elif [[ "$OS" == "Darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install python@3.12
        else
            echo "Homebrew not found. Install Python 3.12+ from https://python.org or install Homebrew first." >&2
            exit 1
        fi
    fi
    PYTHON=python3.12
}

# ── uv ────────────────────────────────────────────────────────────────────────
ensure_uv() {
    if ! command -v uv &>/dev/null; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    fi
}

# ── main ──────────────────────────────────────────────────────────────────────
echo "Installing Agentix into $AGENTIX_HOME ..."
mkdir -p "$AGENTIX_HOME"

ensure_python
ensure_uv

# Build install spec
SPEC="agentix"
if [[ -n "$AGENTIX_VERSION" ]]; then
    SPEC="agentix==$AGENTIX_VERSION"
fi
if [[ -n "$AGENTIX_EXTRAS" ]]; then
    SPEC="${SPEC}[${AGENTIX_EXTRAS}]"
fi

# Create venv and install
uv venv "$VENV" --python "$PYTHON"
uv pip install --python "$VENV/bin/python" "$SPEC"

# Write env activation snippet
ENV_SH="$AGENTIX_HOME/env.sh"
cat > "$ENV_SH" <<EOF
# Source this to activate the Agentix environment:  source ~/.agentix/env.sh
export AGENTIX_HOME="$AGENTIX_HOME"
export PATH="$VENV/bin:\$PATH"
EOF

# Fish shell variant
FISH_DIR="$HOME/.config/fish/conf.d"
if [[ -d "$FISH_DIR" ]]; then
    cat > "$FISH_DIR/agentix.fish" <<EOF
set -gx AGENTIX_HOME "$AGENTIX_HOME"
fish_add_path "$VENV/bin"
EOF
fi

echo ""
echo "Agentix installed: $SPEC"
echo ""
echo "Activate in the current shell:"
echo "  source $ENV_SH"
echo ""
echo "Or add to your shell profile (~/.bashrc / ~/.zshrc):"
echo "  echo 'source $ENV_SH' >> ~/.bashrc"
echo ""
echo "Quickstart: $AGENTIX_HOME/venv/bin/python -c \"import agentix; print(agentix.__version__)\""
echo "Docs: https://github.com/euroblaze/agentix/blob/main/docs/quickstart.md"
