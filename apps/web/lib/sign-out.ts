import { clearClientResponseCache } from '@/lib/api/client';
import { clearPeriods } from '@/lib/period';
import { clearPrimarySchool } from '@/lib/school';

export async function signOutAndRedirect() {
  try {
    await fetch('/auth/signout', { method: 'POST', cache: 'no-store' });
  } finally {
    clearClientResponseCache();
    clearPeriods();
    clearPrimarySchool();
    window.location.replace('/login');
  }
}
