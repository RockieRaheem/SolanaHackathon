import { getPrimarySchool } from '@/lib/school';
import { clientFetch as fetch } from '@/lib/api/client';

export type AcademicPeriod = {
  id: string;
  academic_year_id: string;
  academic_year: number;
  academic_year_name: string;
  name: string;
  sequence: number;
  opening_date: string;
  closing_date: string;
  due_date: string;
  status: 'draft' | 'open' | 'closing' | 'closed';
  is_operational: boolean;
  activity_count: number | null;
  has_close_snapshot?: boolean;
  balance_carry_forward_id?: string | null;
  balance_carried_forward?: boolean;
  balance_carried_into?: boolean;
};

let cachedPeriods: AcademicPeriod[] | null = null;
let pendingPeriods: Promise<AcademicPeriod[]> | null = null;
let cachedDetailedPeriods: AcademicPeriod[] | null = null;
let pendingDetailedPeriods: Promise<AcademicPeriod[]> | null = null;

export async function getAcademicPeriods(includeActivity = false): Promise<AcademicPeriod[]> {
  const cached = includeActivity ? cachedDetailedPeriods : cachedPeriods;
  if (cached) return cached;
  const pending = includeActivity ? pendingDetailedPeriods : pendingPeriods;
  if (pending) return pending;
  const request = getPrimarySchool()
      .then(school => fetch(`/api/backend/api/v1/academic-periods?school_id=${school.id}&include_activity=${includeActivity}`, { cache: 'no-store' }))
      .then(async response => {
        if (!response.ok) throw new Error('Unable to load academic periods');
        const rows = await response.json() as AcademicPeriod[];
        if (includeActivity) cachedDetailedPeriods = rows;
        else cachedPeriods = rows;
        return rows;
      })
      .finally(() => {
        if (includeActivity) pendingDetailedPeriods = null;
        else pendingPeriods = null;
      });
  if (includeActivity) pendingDetailedPeriods = request;
  else pendingPeriods = request;
  return request;
}

export async function getSelectedPeriod(): Promise<AcademicPeriod> {
  const [school, periods] = await Promise.all([getPrimarySchool(), getAcademicPeriods()]);
  if (!periods.length) throw new Error('No academic period has been configured');
  const stored = typeof window === 'undefined' ? null : localStorage.getItem(`harambee-period:${school.id}`);
  const selected = periods.find(period => period.id === stored)
    ?? periods.find(period => period.is_operational)
    ?? periods[0];
  if (typeof window !== 'undefined') localStorage.setItem(`harambee-period:${school.id}`, selected.id);
  return selected;
}

export async function selectPeriod(periodId: string): Promise<void> {
  const school = await getPrimarySchool();
  localStorage.setItem(`harambee-period:${school.id}`, periodId);
}

export function setAcademicPeriods(periods: AcademicPeriod[]): void {
  cachedPeriods = periods;
}

export function clearPeriods(): void {
  cachedPeriods = null;
  pendingPeriods = null;
  cachedDetailedPeriods = null;
  pendingDetailedPeriods = null;
}

export function periodQuery(period: AcademicPeriod): string {
  return `period_id=${encodeURIComponent(period.id)}`;
}
