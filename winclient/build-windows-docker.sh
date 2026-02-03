#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Remote Support Client — Cross-compile to Windows x64 from Linux
#  Uses Docker with the cdrx/pyinstaller-windows image.
#
#  Prerequisites: Docker installed and running
#  Usage: ./build-windows-docker.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_IMAGE="cdrx/pyinstaller-windows:python3"
OUTPUT_DIR="${SCRIPT_DIR}/dist"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Remote Support Client — Docker Cross-Compile"
echo "  Target: Windows x64 (.exe)"
echo "══════════════════════════════════════════════════════════"
echo ""

# ── Check Docker ──────────────────────────────────────────────────────────────
if ! command -v docker &> /dev/null; then
    fail "Docker is required. Install: https://docs.docker.com/get-docker/"
fi

if ! docker info &> /dev/null 2>&1; then
    fail "Docker daemon not running. Start Docker first."
fi

ok "Docker is available."

# ── Pull image ────────────────────────────────────────────────────────────────
info "Pulling Docker image (this may take a while on first run)..."
docker pull "${DOCKER_IMAGE}" --quiet
ok "Docker image ready."

# ── Create temporary build context ────────────────────────────────────────────
BUILD_DIR=$(mktemp -d)
trap "rm -rf ${BUILD_DIR}" EXIT

cp "${SCRIPT_DIR}/client_windows.py" "${BUILD_DIR}/"

# Create requirements file for the build
cat > "${BUILD_DIR}/requirements.txt" <<'EOF'
websockets>=12.0
mss>=9.0
Pillow>=10.0
pyautogui>=0.9.54
pyinstaller>=6.0
EOF

# Create the build entrypoint script
cat > "${BUILD_DIR}/build.sh" <<'BUILDSCRIPT'
#!/bin/bash
set -e
cd /src

echo "[*] Installing Python dependencies..."
pip install --quiet -r requirements.txt

echo "[*] Running PyInstaller..."
pyinstaller \
    --noconfirm \
    --clean \
    --onefile \
    --noconsole \
    --name "RemoteSupportClient" \
    --hidden-import websockets \
    --hidden-import websockets.legacy \
    --hidden-import websockets.legacy.client \
    --hidden-import websockets.legacy.server \
    --hidden-import websockets.legacy.protocol \
    --hidden-import mss \
    --hidden-import mss.windows \
    --hidden-import PIL.Image \
    --hidden-import PIL.JpegImagePlugin \
    --hidden-import pyautogui \
    --hidden-import "pyautogui._pyautogui_win" \
    --hidden-import pyscreeze \
    --hidden-import pytweening \
    --hidden-import pyperclip \
    --hidden-import mouseinfo \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module scipy \
    --exclude-module pandas \
    client_windows.py

echo "[*] Build complete!"
ls -lh dist/RemoteSupportClient.exe
BUILDSCRIPT

chmod +x "${BUILD_DIR}/build.sh"

# ── Run build ─────────────────────────────────────────────────────────────────
info "Building Windows executable inside Docker container..."
echo ""

docker run --rm \
    -v "${BUILD_DIR}:/src" \
    "${DOCKER_IMAGE}" \
    /bin/bash /src/build.sh

# ── Copy output ───────────────────────────────────────────────────────────────
mkdir -p "${OUTPUT_DIR}"
cp "${BUILD_DIR}/dist/RemoteSupportClient.exe" "${OUTPUT_DIR}/RemoteSupportClient.exe"

echo ""
echo "══════════════════════════════════════════════════════════"
echo -e "  ${GREEN}✓ Build successful!${NC}"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "  Output: ${OUTPUT_DIR}/RemoteSupportClient.exe"

EXE_SIZE=$(du -h "${OUTPUT_DIR}/RemoteSupportClient.exe" | cut -f1)
echo "  Size:   ${EXE_SIZE}"

echo ""
echo "  Usage:"
echo "    RemoteSupportClient.exe"
echo "    RemoteSupportClient.exe --server ws://192.168.1.100:3000"
echo "    RemoteSupportClient.exe --server ws://myserver.com:3000 --fps 15"
echo ""
