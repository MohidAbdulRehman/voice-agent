#!/usr/bin/env bash
# Smoke-check a running API:  bash scripts/smoke.sh https://<project>.vercel.app
#
# Walks health, list, create, get, update, search and delete, plus the 400, 404
# and 422 cases, checking every status code and the {data, error} envelope with
# jq. It registers one fictional patient (a 555-01XX number, an example.com
# email) and soft-deletes it again, even when a check fails. Exits non-zero on
# the first mismatch. Needs bash, curl and jq.
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
command -v jq >/dev/null || { echo "smoke: jq is required" >&2; exit 2; }

body="$(mktemp)"
headers="$(mktemp)"
created=""
checks=0

cleanup() {
  if [[ -n "$created" ]]; then
    curl --silent --output /dev/null --request DELETE "$BASE_URL/patients/$created" || true
  fi
  rm -f "$body" "$headers"
}
trap cleanup EXIT

fail() {
  echo "FAIL $*" >&2
  exit 1
}

# call METHOD PATH STATUS [JSON]: send a request, then check its status and envelope.
call() {
  local method="$1" path="$2" expected="$3" data="${4-}" status
  local args=(--silent --show-error --max-time 90 --request "$method"
    --output "$body" --dump-header "$headers" --write-out '%{http_code}')
  if [[ -n "$data" ]]; then
    args+=(--header "Content-Type: application/json" --data "$data")
  fi
  status="$(curl "${args[@]}" "$BASE_URL$path")" || fail "$method $path: no response"
  [[ "$status" == "$expected" ]] ||
    fail "$method $path: expected $expected, got $status: $(head -c 300 "$body")"
  jq -e 'type == "object" and keys == ["data", "error"]' "$body" >/dev/null ||
    fail "$method $path: not a {data, error} envelope: $(head -c 300 "$body")"
  if ((expected < 400)); then
    expect '.error == null' "$method $path: error should be null"
  else
    expect '.data == null and (.error | has("code") and has("message") and has("details"))' \
      "$method $path: malformed error"
  fi
  checks=$((checks + 1))
  echo "ok   $method $path -> $status"
}

# expect FILTER WHAT: the last response body must satisfy the jq FILTER.
expect() {
  jq -e "$1" "$body" >/dev/null || fail "$2: $(head -c 300 "$body")"
}

echo "Smoke-checking $BASE_URL"

call GET /health 200
expect '.data.status == "ok" and .data.database == "ok"' "health"

call GET "/patients?limit=5" 200
expect '.data | type == "array"' "list"

call POST /patients 201 '{"first_name": "Smoke", "last_name": "Check",
  "date_of_birth": "01/02/1985", "sex": "Other", "phone_number": "(212) 555-0199",
  "email": "smoke.check@example.com", "address_line_1": "1 Test Way", "city": "Austin",
  "state": "TX", "zip_code": "78701"}'
expect '.data.phone_number == "2125550199" and .data.date_of_birth == "01/02/1985"
  and .data.preferred_language == "English"' "create normalizes and fills defaults"
created="$(jq -r '.data.patient_id' "$body")"
grep -qi "^location: /patients/$created" "$headers" || fail "POST /patients: no Location header"

call GET "/patients/$created" 200
expect ".data.patient_id == \"$created\"" "get returns the patient"

call PUT "/patients/$created" 200 '{"city": "Dallas"}'
expect '.data.city == "Dallas" and .data.last_name == "Check"' "update changes only city"

call GET "/patients?last_name=check&phone_number=212-555-0199" 200
expect "[.data[].patient_id] | index(\"$created\") != null" "search finds the patient"

call POST /patients 422 '{"first_name": "Smoke", "date_of_birth": "01/01/2999"}'
expect '.error.code == "VALIDATION_ERROR"
  and ([.error.details[].field] | index("date_of_birth") != null)' "validation details"

call GET "/patients?date_of_birth=1985-01-02" 400
expect '.error.code == "BAD_REQUEST"' "a bad query parameter"

call GET /patients/not-a-uuid 400
call POST /patients 400 '{"first_name": '
call GET /patients/00000000-0000-4000-8000-00000000dead 404
expect '.error.code == "NOT_FOUND"' "unknown patient"

call DELETE "/patients/$created" 200
expect '.data.deleted_at != null' "delete sets deleted_at"
deleted="$created"
created=""
call GET "/patients/$deleted" 404
call DELETE "/patients/$deleted" 404

call GET /doctors 200
expect '.data | length > 0' "seeded doctors"
call GET "/calls?limit=5" 200
expect '.data | type == "array"' "calls"

status="$(curl --silent --output /dev/null --write-out '%{http_code}' "$BASE_URL/dashboard/")"
[[ "$status" == "200" ]] || fail "GET /dashboard/: expected 200, got $status"
echo "ok   GET /dashboard/ -> 200"

echo "All $((checks + 1)) checks passed against $BASE_URL"
