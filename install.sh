#!/usr/bin/env bash
# install.sh - installs CS Framework on Linux / macOS
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
CS_PY="$HERE/cs.py"
[ -f "$CS_PY" ] || { echo "cs.py not found next to this script"; exit 1; }

head() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf '  [+] %s\n' "$1"; }
warn() { printf '  [!] %s\n' "$1"; }
err()  { printf '  [X] %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

head "1. detecting package manager"
PM=""
if   have apt;    then PM=apt
elif have dnf;    then PM=dnf
elif have yum;    then PM=yum
elif have pacman; then PM=pacman
elif have brew;   then PM=brew
else err "no supported package manager"; exit 1
fi
ok "using $PM"

inst() {
    pkg="$1"
    case "$PM" in
        apt)    sudo apt-get update -y && sudo apt-get install -y "$pkg" ;;
        dnf|yum) sudo "$PM" install -y "$pkg" ;;
        pacman) sudo pacman -S --noconfirm "$pkg" ;;
        brew)   brew install "$pkg" ;;
    esac
}

head "2. prerequisites"
have python3 || inst python3
have pip3    || { case "$PM" in apt|dnf|yum) inst python3-pip ;; *) inst pip3 ;; esac; }
have git     || inst git
have cmake   || inst cmake
have ninja   || inst ninja
have curl    || inst curl

# build tools
if [ "$PM" = "apt" ]; then
    sudo apt-get install -y build-essential
elif [ "$PM" = "dnf" ] || [ "$PM" = "yum" ]; then
    sudo "$PM" groupinstall -y "Development Tools"
fi

ok "prerequisites done"

head "3. CUDA (skip if no NVIDIA GPU)"
if command -v nvidia-smi >/dev/null 2>&1; then
    if have nvcc; then
        ok "nvcc: $(command -v nvcc)"
    else
        warn "nvcc missing. install CUDA 12.4 from:"
        echo "    https://developer.nvidia.com/cuda-12-4-0-download-archive"
    fi
else
    warn "no NVIDIA GPU; skipping CUDA"
fi

head "4. Ollama (optional)"
if have ollama; then
    ok "ollama present"
else
    printf "  install ollama? [y/N] "
    read -r ans
    case "$ans" in
        y|Y) curl -fsSL https://ollama.com/install.sh | sh ;;
        *) warn "skipping ollama" ;;
    esac
fi

head "5. PrismML fork (ternary kernels for Bonsai 2)"
python3 "$CS_PY" install prism-fork

head "6. initial setup"
python3 "$CS_PY" setup --quiet

head "7. verify"
python3 "$CS_PY" selftest
python3 "$CS_PY" doctor

head "DONE"
echo "  run: cs"