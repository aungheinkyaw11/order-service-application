#!/bin/sh
set -eu

base_url="${BASE_URL:-http://localhost:8000}"
request_id="${REQUEST_ID:-$(python -c 'import uuid; print(uuid.uuid4())')}"

curl --fail --silent --show-error "$base_url/health"
printf '\n'
curl --fail --silent --show-error "$base_url/ready"
printf '\n'

response="$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -H "X-Request-ID: $request_id" \
  -d '{"symbol":"AAPL","quantity":5}' \
  "$base_url/orders")"
order_id="$(printf '%s' "$response" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

printf 'created request_id=%s order_id=%s response=%s\n' "$request_id" "$order_id" "$response"
printf 'initial: '
curl --fail --silent --show-error "$base_url/orders/$order_id"
printf '\n'

sleep 3
printf 'after processing: '
final="$(curl --fail --silent --show-error "$base_url/orders/$order_id")"
printf '%s\n' "$final"
printf '%s' "$final" | python -c \
  'import json,sys; assert json.load(sys.stdin)["status"] == "filled", "order was not filled"'

printf '\ncorrelated logs:\n'
docker compose logs api worker | grep "$request_id"