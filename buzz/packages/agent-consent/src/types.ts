export interface ConsentGrant {
  scopes: Array<'mic' | 'camera' | 'record' | 'tools_during_call'>;
  record: boolean;
  server_processing_opt_in: boolean;
  expiration: number;
}

export function validateConsent(grant: ConsentGrant | null, requiredScopes: string[]): boolean {
  if (!grant) return false;
  const now = Math.floor(Date.now() / 1000);
  if (grant.expiration <= now) return false;
  return requiredScopes.every(scope => grant.scopes.includes(scope as any));
}
