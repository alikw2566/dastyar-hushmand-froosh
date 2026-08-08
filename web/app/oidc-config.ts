export function oidcExternalIssuer(): string | null {
  return process.env.OIDC_ISSUER ?? null;
}

export function oidcInternalIssuer(): string | null {
  return process.env.OIDC_INTERNAL_ISSUER ?? oidcExternalIssuer();
}

export function oidcClientId(): string {
  return process.env.OIDC_CLIENT_ID ?? "mokalemeban-web";
}
