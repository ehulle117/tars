#!/usr/bin/env bash
# Checks apps/network-policies.yaml and the deluge Service split behave as
# intended. Run from a machine on the LAN with kubectl access, after Argo has
# synced. Every line should say "ok".
set -u
ok=0; bad=0
expect() { # expect <want: open|closed> <label> <cmd...>
  local want=$1 label=$2; shift 2
  if "$@" >/dev/null 2>&1; then got=open; else got=closed; fi
  if [ "$got" = "$want" ]; then echo "ok    $label ($got)"; ok=$((ok+1)); else echo "FAIL  $label (want $want, got $got)"; bad=$((bad+1)); fi
}
from() { local app=$1; shift; kubectl -n apps exec "deploy/$app" -c "$app" -- "$@"; }
tcp() { curl -s -o /dev/null -m 5 "http://$1/"; }

# LAN -> LoadBalancer services still work (trusted and untrusted targets)
expect open   "LAN -> sonarr :8989"          tcp 192.168.8.103:8989
expect open   "LAN -> deluge web :8112"      tcp 192.168.8.103:8112
expect open   "LAN -> mead :8770"            tcp 192.168.8.103:8770
expect open   "LAN -> NPM sonarr.tars.local" curl -sf -o /dev/null -m 5 -H "Host: sonarr.tars.local" http://192.168.8.250/
# Deluge's daemon and Privoxy are no longer on the LAN
expect closed "LAN -> deluge daemon :58846"  nc -z -w 3 192.168.8.103 58846
expect closed "LAN -> privoxy :8118"         nc -z -w 3 192.168.8.103 8118

# Trusted pods -> untrusted pods still work
expect open   "sonarr -> deluge-svc:8112"       from sonarr curl -s -o /dev/null -m 5 http://deluge-svc:8112/
expect open   "prowlarr -> flaresolverr-svc"    from prowlarr curl -s -o /dev/null -m 5 http://flaresolverr-svc:8191/

# Untrusted pods can't reach other pods or the LAN, but can reach the internet
# (deluge's own VPN firewall already blocks the LAN, so flaresolverr is the
# meaningful test here)
expect closed "flaresolverr -> sonarr-svc:8989" from flaresolverr curl -s -o /dev/null -m 5 http://sonarr-svc:8989/
expect closed "flaresolverr -> router"          from flaresolverr curl -s -o /dev/null -m 5 http://192.168.8.1/
expect closed "flaresolverr -> Case"            from flaresolverr curl -s -o /dev/null -m 5 http://192.168.8.152/
expect open   "flaresolverr -> internet"        from flaresolverr curl -s -o /dev/null -m 10 https://example.com/

echo "$ok ok, $bad failed"; kubectl -n apps get pods | grep -vE 'Running|Completed' || true
[ "$bad" -eq 0 ]
