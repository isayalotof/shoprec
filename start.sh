#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
printf '%s\n' 'Open http://127.0.0.1:8787 after the server starts.' 'Admin: /admin. The initial token is stored in data/admin-token.'
exec python3 server.py "$@"
