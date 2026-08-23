#!/bin/bash

############################################################################
#
#    Virtual Environment Setup
#
#    Usage: ./scripts/venv_setup.sh
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
VENV_DIR="${REPO_ROOT}/.venv"

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

if [[ ! -t 1 || -n "${NO_COLOR:-}" ]]; then
    ORANGE=''
    DIM=''
    BOLD=''
    NC=''
fi

echo ""
echo -e "${ORANGE}"
cat << 'BANNER'
     █████╗  ██████╗ ███╗   ██╗ ██████╗
    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
    ███████║██║  ███╗██╔██╗ ██║██║   ██║
    ██╔══██║██║   ██║██║╚██╗██║██║   ██║
    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝
BANNER
echo -e "${NC}"
echo -e "    ${DIM}ARC-AGI Environment Setup${NC}"
echo ""

# Preflight
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo "    Deactivate the current virtual environment first."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "    uv not found. Install: https://docs.astral.sh/uv/"
    exit 1
fi

# Setup
echo -e "    ${DIM}Removing old environment...${NC}"
echo -e "    ${DIM}> rm -rf ${VENV_DIR}${NC}"
rm -rf "${VENV_DIR}"

echo ""
echo -e "    ${DIM}Creating Python 3.12 venv...${NC}"
echo -e "    ${DIM}> uv venv ${VENV_DIR} --python 3.12${NC}"
uv venv "${VENV_DIR}" --python 3.12 --quiet

echo ""
echo -e "    ${DIM}Installing pinned requirements...${NC}"
echo -e "    ${DIM}> uv pip install -r requirements.txt${NC}"
uv pip install --python "${VENV_DIR}/bin/python" -r "${REPO_ROOT}/requirements.txt" --quiet

echo ""
echo -e "    ${DIM}Installing the arcade (editable) — this is what makes \`play\` a command...${NC}"
echo -e "    ${DIM}> uv pip install -e . --no-deps${NC}"
uv pip install --python "${VENV_DIR}/bin/python" -e "${REPO_ROOT}" --no-deps --quiet

echo ""
echo -e "    ${BOLD}Done.${NC}"
echo ""
echo -e "    ${DIM}Activate:${NC}  source .venv/bin/activate"
echo ""
