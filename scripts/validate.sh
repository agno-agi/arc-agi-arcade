#!/bin/bash

############################################################################
#
#    Workspace Validator
#
#    Usage: ./scripts/validate.sh
#
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"

# Colors
ORANGE='\033[38;5;208m'
RED='\033[31m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

if [[ ! -t 1 || -n "${NO_COLOR:-}" ]]; then
    ORANGE=''
    RED=''
    DIM=''
    BOLD=''
    NC=''
fi

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo -e "${RED}Warning:${NC} no virtualenv active. Run: ${BOLD}source .venv/bin/activate${NC}"
    echo ""
fi

echo ""
echo -e "${ORANGE}▸${NC} ${BOLD}Validating ARC workspace${NC}"
echo ""

failed=0

# Prefer the project venv; fall back to PATH (CI installs with --system).
RUFF="${REPO_ROOT}/.venv/bin/ruff"; command -v "${RUFF}" >/dev/null 2>&1 || RUFF="ruff"
MYPY="${REPO_ROOT}/.venv/bin/mypy"; command -v "${MYPY}" >/dev/null 2>&1 || MYPY="mypy"

echo -e "${DIM}> ruff check ${REPO_ROOT}${NC}"
if ! "${RUFF}" check "${REPO_ROOT}"; then
    failed=1
fi

echo ""
echo -e "${DIM}> mypy ${REPO_ROOT}${NC}"
if ! "${MYPY}" "${REPO_ROOT}" --config-file "${REPO_ROOT}/pyproject.toml"; then
    failed=1
fi

echo ""
if [[ ${failed} -eq 0 ]]; then
    echo -e "${BOLD}Done.${NC}"
else
    echo -e "${RED}${BOLD}Failed.${NC}"
fi
echo ""

exit "${failed}"
