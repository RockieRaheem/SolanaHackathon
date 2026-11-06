import { clientFetch as fetch } from '@/lib/api/client';
import { AcademicPeriod, setAcademicPeriods } from '@/lib/period';
import { School, SchoolLoadError, setPrimarySchool } from '@/lib/school';

export type DashboardActivity = {
  id: string;
  occurredAt: string;
  learner: string;
  learnerRef: string;
  description: string;
  amount: number;
  currency: 'UGX';
  status: 'RECONCILED' | 'MATCH_SUGGESTED' | 'SETTLED' | 'UNMATCHED';
};

export type DashboardOverview = {
  mode: 'DEMO' | 'LIVE';
  school: { id: string; name: string };
  period: { id: string; label: string };
  generatedAt: string;
  metrics: { billed: number; collected: number; outstanding: number; activeLearners: number; accountsInArrears: number; unreconciledCount: number; suggestedMatches: number };
  weeklyCollections: number[];
  activity: DashboardActivity[];
  attention: { id: string; kind: string; title: string; detail: string; occurredAt: string }[];
};

export type DashboardBootstrap = {
  school: School;
  periods: AcademicPeriod[];
  overview: DashboardOverview;
};

let pendingBootstrap: Promise<DashboardBootstrap> | null = null;

export function getDashboardBootstrap(): Promise<DashboardBootstrap> {
  if (!pendingBootstrap) {
    pendingBootstrap = fetch('/api/backend/api/v1/dashboard/bootstrap', { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) {
          const body = await response.json().catch(() => null) as { detail?: string } | null;
          throw new SchoolLoadError(response.status, body?.detail ?? 'Dashboard is unavailable');
        }
        const result = await response.json() as DashboardBootstrap;
        setPrimarySchool(result.school);
        setAcademicPeriods(result.periods);
        return result;
      })
      .finally(() => { pendingBootstrap = null; });
  }
  return pendingBootstrap;
}
