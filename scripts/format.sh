#!/bin/bash

############################################################################
#
#    Workspace Formatter
#
#    Usage: ./scripts/format.sh
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"

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
echo -e "${ORANGE}▸${NC} ${BOLD}Formatting ARC workspace${NC}"
echo ""

echo -e "${DIM}> ruff format ${REPO_ROOT}${NC}"
"${REPO_ROOT}/.venv/bin/ruff" format "${REPO_ROOT}"

echo ""
echo -e "${DIM}> ruff check --select I --fix ${REPO_ROOT}${NC}"
"${REPO_ROOT}/.venv/bin/ruff" check --select I --fix "${REPO_ROOT}"

echo ""
echo -e "${BOLD}Done.${NC}"
echo ""
