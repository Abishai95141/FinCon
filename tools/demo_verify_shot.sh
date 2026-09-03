#!/usr/bin/env bash
# Shot 9 — check it without us.
#
# Run this in a terminal you are screen-recording, full screen, large type, dark
# theme. It types itself at a readable pace and pauses where the narration needs
# a beat.
#
# Deliberately points at the DEPLOYED host, not localhost. The whole claim of
# this shot is that a stranger on the internet can check our arithmetic without
# an account, so the hostname on screen has to be the real one — a demo of that
# claim against 127.0.0.1 would be demonstrating something else.
#
#   asciinema rec demo/verify.cast -c tools/demo_verify_shot.sh
# or just screen-record the window and trim.

set -euo pipefail

BASE="${FINCON_BASE:-https://fincon.astutecomputer.com}"
PROOF="${FINCON_PROOF:-docs/sample-proof.json}"

type_out() {          # echo, one character at a time, like a person
  local s="$1"
  printf '$ '
  for ((i = 0; i < ${#s}; i++)); do
    printf '%s' "${s:i:1}"
    sleep 0.028
  done
  printf '\n'
}

beat() { sleep "${1:-1.2}"; }

clear
beat 0.8

# --- the honest case ------------------------------------------------------
type_out "curl -s -X POST $BASE/v1/verify \\"
type_out "     -H 'content-type: application/json' -d @$PROOF | jq '{proven, recomputed_residual, policy_source}'"
beat 0.5
curl -s -X POST "$BASE/v1/verify" \
  -H 'content-type: application/json' -d "@$PROOF" \
  | jq '{proven, recomputed_residual, policy_source}'
beat 2.6

# --- the same proof, one number changed -----------------------------------
type_out "# change one amount and ask again"
beat 0.7

TAMPERED="$(mktemp -t fincon-tampered).json"
# Bend the first leg subtotal by a rupee. Small enough that nothing about the
# document looks wrong, large enough that the arithmetic stops closing — which
# is the point: the refusal is not spotting a malformed file, it is re-deriving
# the sum and finding it does not add up.
jq '(.proof.legs[0].subtotal) |= ((tonumber + 1) | tostring)' "$PROOF" > "$TAMPERED"

type_out "curl -s -X POST $BASE/v1/verify -d @tampered.json | jq '{proven, reasons}'"
beat 0.5
curl -s -X POST "$BASE/v1/verify" \
  -H 'content-type: application/json' -d "@$TAMPERED" \
  | jq '{proven, reasons}'
beat 3.4

rm -f "$TAMPERED"
