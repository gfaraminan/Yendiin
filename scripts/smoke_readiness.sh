#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=. pytest -q tests/test_public_config_contract.py tests/test_smoke_checkout_auth_mp.py
node frontend/scripts/smoke_flag_views.mjs
npm --prefix frontend run build
