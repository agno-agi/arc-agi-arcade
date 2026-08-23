#!/bin/bash

############################################################################
#
#    Requirements Generator
#
#    Usage:
#      ./scripts/generate_requirements.sh           # Generate
#      ./scripts/generate_requirements.sh upgrade   # Generate with upgrade
#      ./scripts/generate_requirements.sh <pkg>...  # Refresh only these pins
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
echo -e "    ${ORANGE}▸${NC} ${BOLD}Generating requirements.txt${NC}"
echo ""

if [[ "${1:-}" = "upgrade" ]]; then
    echo -e "    ${DIM}Mode: upgrade${NC}"
    echo -e "    ${DIM}> uv pip compile pyproject.toml --extra dev --python-version 3.12 --no-cache --upgrade -o requirements.txt${NC}"
    echo ""
    UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh upgrade" \
        uv pip compile "${REPO_ROOT}/pyproject.toml" --extra dev --python-version 3.12 \
        --no-cache --upgrade --output-file "${REPO_ROOT}/requirements.txt"
elif [[ $# -gt 0 ]]; then
    upgrade_flags=()
    for package in "$@"; do
        upgrade_flags+=("--upgrade-package" "${package}")
    done
    echo -e "    ${DIM}Mode: refresh ($*)${NC}"
    echo -e "    ${DIM}> uv pip compile pyproject.toml --extra dev --python-version 3.12 --no-cache ${upgrade_flags[*]} -o requirements.txt${NC}"
    echo ""
    UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh" \
        uv pip compile "${REPO_ROOT}/pyproject.toml" --extra dev --python-version 3.12 \
        --no-cache "${upgrade_flags[@]}" --output-file "${REPO_ROOT}/requirements.txt"
else
    echo -e "    ${DIM}Mode: standard${NC}"
    echo -e "    ${DIM}> uv pip compile pyproject.toml --extra dev --python-version 3.12 --no-cache -o requirements.txt${NC}"
    echo ""
    UV_CUSTOM_COMPILE_COMMAND="./scripts/generate_requirements.sh" \
        uv pip compile "${REPO_ROOT}/pyproject.toml" --extra dev --python-version 3.12 \
        --no-cache --output-file "${REPO_ROOT}/requirements.txt"
fi

echo ""
echo -e "    ${BOLD}Done.${NC}"
echo ""
