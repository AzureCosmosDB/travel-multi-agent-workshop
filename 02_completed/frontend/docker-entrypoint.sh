#!/bin/sh
set -e

# Substitute only API_BASE_URL in the nginx config template
envsubst '${API_BASE_URL}' < /etc/nginx/nginx.conf.template > /etc/nginx/conf.d/default.conf

exec "$@"
