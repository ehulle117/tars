#!/usr/bin/env bash
# Rotates Homarr's SECRET_ENCRYPTION_KEY and (re)creates the homarr-secrets
# Secret in the apps namespace. Run this wherever your kubeconfig for the
# Tars cluster lives (NOT on Case — Case has no Kubernetes control plane).
#
# Usage: ./scripts/rotate-homarr-secret.sh
set -euo pipefail

NAMESPACE="apps"
SECRET_NAME="homarr-secrets"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found on this machine. Run this from wherever you manage Tars." >&2
  exit 1
fi

if ! kubectl config current-context >/dev/null 2>&1; then
  echo "No active kubectl context. Point your kubeconfig at the Tars cluster first." >&2
  exit 1
fi

echo "Current kubectl context: $(kubectl config current-context)"
read -rp "Apply the new secret to this context? [y/N] " confirm
if [[ "${confirm,,}" != "y" ]]; then
  echo "Aborted."
  exit 1
fi

NEW_KEY="$(openssl rand -hex 32)"

kubectl create secret generic "$SECRET_NAME" \
  --namespace "$NAMESPACE" \
  --from-literal=SECRET_ENCRYPTION_KEY="$NEW_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret '$SECRET_NAME' created/updated in namespace '$NAMESPACE'."
echo "Restarting homarr deployment to pick up the new key..."
kubectl rollout restart deployment/homarr -n "$NAMESPACE"

echo "Done. Note: this invalidates Homarr's previously encrypted config"
echo "(integration credentials, etc.) — you'll need to re-enter those in the UI."
