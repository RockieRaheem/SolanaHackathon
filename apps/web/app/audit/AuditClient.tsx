'use client';

import { useEffect, useMemo, useState } from 'react';
import { Activity, Database, History, ShieldCheck } from 'lucide-react';
import { FilterSearch, MetricCard, PageHeader, RegisterFilters, SectionHeader, Status } from '@/components/ui';
import { getPrimarySchool } from '@/lib/school';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Event = { id:string; entity_type:string; entity_id:string; action:string; actor:string; summary:string; occurred_at:string };

export default function AuditClient() {
  const [events, setEvents] = useState<Event[]>([]);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [action, setAction] = useState('all');
  const [period, setPeriod] = useState('all');
  const [error, setError] = useState('');

  useEffect(() => {
    getPrimarySchool()
      .then(school => fetch(`${API}/api/v1/audit-events?school_id=${school.id}&limit=500`))
      .then(response => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then(setEvents)
      .catch(() => setError('Audit service is unavailable.'));
  }, []);

  const types = Array.from(new Set(events.map(event => event.entity_type))).sort();
  const actions = Array.from(new Set(events.map(event => event.action))).sort();
  const visible = useMemo(
    () => events.filter(event => {
      const age = Date.now() - new Date(event.occurred_at).getTime();
      const matchesPeriod = period === 'all' || age <= Number(period) * 86_400_000;
      return (kind === 'all' || event.entity_type === kind) &&
        (action === 'all' || event.action === action) && matchesPeriod &&
        `${event.summary} ${event.actor} ${event.entity_type} ${event.entity_id} ${event.action}`.toLowerCase().includes(query.toLowerCase());
    }),
    [action, events, kind, period, query]
  );
  const today = events.filter(event => new Date(event.occurred_at).toDateString() === new Date().toDateString()).length;

  return <>
    <PageHeader eyebrow="Governance · Immutable accountability" title="Operational audit trail" description="Append-only evidence of consequential learner and financial record changes." />
    {error && <div className="form-error page-error">{error}</div>}
    <section className="metric-grid">
      <MetricCard icon={History} label="Recorded events" value={String(events.length)} note="Latest 500 school events" tone="blue" />
      <MetricCard icon={Activity} label="Activity today" value={String(today)} note="Current local calendar day" tone="green" />
      <MetricCard icon={Database} label="Covered records" value={String(types.length)} note="Operational entity types" tone="amber" />
      <MetricCard icon={ShieldCheck} label="Integrity" value="Append-only" note="Updates and deletes blocked" />
    </section>
    <section className="panel">
      <SectionHeader title="Event register" subtitle="Database triggers record inserts and updates in the same transaction." />
      <RegisterFilters shown={visible.length} total={events.length} active={Boolean(query || kind !== 'all' || action !== 'all' || period !== 'all')} onReset={() => { setQuery(''); setKind('all'); setAction('all'); setPeriod('all'); }}>
        <FilterSearch value={query} onChange={setQuery} placeholder="Search event, actor or identifier" />
        <select className="select-control" value={kind} onChange={event => setKind(event.target.value)}>
          <option value="all">All records</option>
          {types.map(type => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
        </select>
        <select className="select-control" aria-label="Audit action" value={action} onChange={event => setAction(event.target.value)}><option value="all">All actions</option>{actions.map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select>
        <select className="select-control" aria-label="Audit period" value={period} onChange={event => setPeriod(event.target.value)}><option value="all">Any time</option><option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select>
      </RegisterFilters>
      <div className="table-wrap"><table className="data-table">
        <thead><tr><th>Time</th><th>Event</th><th>Record</th><th>Actor</th><th>Integrity</th></tr></thead>
        <tbody>
          {visible.map(event => <tr key={event.id}>
            <td className="entity"><strong>{new Date(event.occurred_at).toLocaleDateString('en-UG')}</strong><small>{new Date(event.occurred_at).toLocaleTimeString('en-UG')}</small></td>
            <td className="entity"><strong>{event.summary}</strong><small>{event.entity_type.replaceAll('_', ' ')}</small></td>
            <td><code>{event.entity_id.slice(0, 8)}…</code></td><td>{event.actor}</td><td><Status tone="success">Recorded</Status></td>
          </tr>)}
          {!visible.length && <tr><td colSpan={5}><div className="empty-register"><History /><strong>No audit events found</strong><span>New operational changes will appear here automatically.</span></div></td></tr>}
        </tbody>
      </table></div>
    </section>
  </>;
}
