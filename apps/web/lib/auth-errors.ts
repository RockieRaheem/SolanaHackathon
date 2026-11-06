type AuthFailure = { code?: string; message?: string; status?: number };

const messages: Record<string, string> = {
  anonymous_provider_disabled: 'Account creation is currently unavailable. Please contact your administrator.',
  email_address_invalid: 'Enter a valid email address.',
  email_not_confirmed: 'Confirm your email address before signing in. Check your inbox and spam folder.',
  email_provider_disabled: 'Email sign-in is not enabled for this service.',
  flow_state_expired: 'This sign-in attempt expired. Please start again.',
  flow_state_not_found: 'This sign-in attempt could not be verified. Please start again.',
  invalid_credentials: 'The email address or password is incorrect.',
  oauth_failed: 'Google could not complete the sign-in. Please try again.',
  oauth_timeout: 'Google sign-in took too long. Please start again.',
  over_email_send_rate_limit: 'Too many emails were requested. Wait a few minutes before trying again.',
  over_request_rate_limit: 'Too many attempts were made. Wait a moment before trying again.',
  session_expired: 'Your secure session has ended. Sign in again to continue.',
  signup_disabled: 'New account registration is currently closed.',
  user_already_exists: 'An account already exists for this email address. Sign in instead.',
  user_banned: 'This account cannot sign in. Contact your administrator for assistance.',
  weak_password: 'Choose a stronger password with at least 10 characters, including a letter and a number.',
};

export function authMessage(reason: unknown, fallback = 'We could not complete that request. Please try again.') {
  if (typeof reason === 'string') return messages[reason] ?? fallback;
  if (!reason || typeof reason !== 'object') return fallback;
  const failure = reason as AuthFailure;
  if (failure.code && messages[failure.code]) return messages[failure.code];
  if (failure.status === 429) return messages.over_request_rate_limit;
  return fallback;
}

export function authMessageFromCode(code: string | string[] | undefined) {
  const value = Array.isArray(code) ? code[0] : code;
  return value ? messages[value] ?? '' : '';
}
