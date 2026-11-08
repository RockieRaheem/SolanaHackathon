const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function normalizeEmail(value: unknown) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

export function validEmail(email: string) {
  return email.length <= 254 && EMAIL_PATTERN.test(email);
}

export function passwordProblem(password: string) {
  if (password.length < 12) return 'Use at least 12 characters for your password.';
  if (!/[a-z]/.test(password)) return 'Include at least one lowercase letter.';
  if (!/[A-Z]/.test(password)) return 'Include at least one uppercase letter.';
  if (!/\d/.test(password)) return 'Include at least one number.';
  if (!/[^A-Za-z0-9]/.test(password)) return 'Include at least one symbol.';
  return '';
}

export function safeNextPath(value: unknown, fallback = '/workspace') {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return fallback;
  if (value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value)) return fallback;
  return value;
}
