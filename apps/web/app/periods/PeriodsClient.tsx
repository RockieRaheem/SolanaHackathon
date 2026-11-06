'use client';

import { AlertTriangle, ArrowRightLeft, ArrowUpRight, CalendarDays, CheckCircle2, Edit3, LoaderCircle, LockKeyhole, Plus, RefreshCw, ShieldCheck, Trash2, X } from 'lucide-react';
import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { PageHeader } from '@/components/ui';
import { AcademicPeriod, clearPeriods, getAcademicPeriods, selectPeriod } from '@/lib/period';
import { getPrimarySchool, School } from '@/lib/school';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type TermDraft = { name: string; opening_date: string; due_date: string; closing_date: string };
type CloseControl = { code:string; title:string; status:'passed'|'blocked'|'warning'; detail:string; count:number; amount:string|number; action_href:string };
type CloseReadiness = { period:AcademicPeriod; ready_to_close:boolean; blocker_count:number; warning_count:number; controls:CloseControl[] };
type CloseSummary = { id:string; period_id:string; snapshot_hash:string; snapshot_version:number; learner_count:number; warning_count:number; opening_balance:string|number; net_assessed:string|number; net_collected:string|number; period_activity:string|number; closing_balance:string|number; outstanding:string|number; credit_balance:string|number; closed_by:string; closed_at:string };
type TransitionResult = AcademicPeriod & { close_summary?:CloseSummary; idempotent_replay?:boolean };
type CarryLine = { student_id:string; admission_no:string; learner_name:string; amount:string|number; balance_type:'debt'|'credit'; ledger_entry_id:string };
type CarrySummary = { id:string; source_period_id:string; source_period_name:string; source_academic_year_name:string; destination_period_id:string; destination_period_name:string; destination_academic_year_name:string; source_snapshot_hash:string; learner_count:number; debt_total:string|number; credit_total:string|number; net_balance:string|number; posted_by:string; posted_at:string; lines:CarryLine[]; idempotent_replay?:boolean };
type CarryPreview = { already_posted:false; source_period:AcademicPeriod; destination_period:AcademicPeriod; source_close_id:string; source_snapshot_hash:string; learner_count:number; debt_learner_count:number; credit_learner_count:number; debt_total:string|number; credit_total:string|number; net_balance:string|number; conflicting_opening_count:number; ready_to_post:boolean };
const blankTerms = (): TermDraft[] => ['Term 1', 'Term 2', 'Term 3'].map(name => ({ name, opening_date: '', due_date: '', closing_date: '' }));
const money = (value:string|number) => `UGX ${Number(value).toLocaleString('en-UG',{maximumFractionDigits:0})}`;

export default function PeriodsClient() {
  const [school, setSchool] = useState<School | null>(null);
  const [periods, setPeriods] = useState<AcademicPeriod[]>([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AcademicPeriod | null>(null);
  const [terms, setTerms] = useState<TermDraft[]>(blankTerms);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [closingPeriod, setClosingPeriod] = useState<AcademicPeriod | null>(null);
  const [readiness, setReadiness] = useState<CloseReadiness | null>(null);
  const [checkingClose, setCheckingClose] = useState(false);
  const [closeSummary, setCloseSummary] = useState<CloseSummary | null>(null);
  const [summaryPeriod, setSummaryPeriod] = useState<AcademicPeriod | null>(null);
  const [carrySource, setCarrySource] = useState<AcademicPeriod | null>(null);
  const [carryDestination, setCarryDestination] = useState<AcademicPeriod | null>(null);
  const [carryPreview, setCarryPreview] = useState<CarryPreview | null>(null);
  const [carrySummary, setCarrySummary] = useState<CarrySummary | null>(null);
  const [checkingCarry, setCheckingCarry] = useState(false);
  const [postingCarry, setPostingCarry] = useState(false);

  async function load() {
    setLoading(true); setError(''); clearPeriods();
    try {
      const [institution, rows] = await Promise.all([getPrimarySchool(), getAcademicPeriods(true)]);
      setSchool(institution); setPeriods(rows);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Calendar unavailable'); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  const operational = useMemo(() => periods.find(item => item.is_operational), [periods]);
  const canManageCarry = school?.role === 'owner' || school?.role === 'bursar';

  function nextConfiguredPeriod(source: AcademicPeriod) {
    return [...periods]
      .filter(period => period.academic_year > source.academic_year || (period.academic_year === source.academic_year && period.sequence > source.sequence))
      .sort((a,b) => a.academic_year - b.academic_year || a.sequence - b.sequence)[0] ?? null;
  }

  function responseError(body:unknown, fallback:string) {
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as {detail?:unknown}).detail;
      if (typeof detail === 'string') return detail;
      if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as {message?:unknown}).message === 'string') return (detail as {message:string}).message;
    }
    return fallback;
  }

  async function createYear(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!school) return; setSaving(true); setError('');
    const form = new FormData(event.currentTarget);
    const year = Number(form.get('year'));
    const response = await fetch(`${API}/api/v1/academic-years`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ school_id: school.id, name: form.get('name'), year, start_date: form.get('start_date'), end_date: form.get('end_date'), periods: terms.map((term, index) => ({ ...term, sequence: index + 1 })) }) });
    if (!response.ok) { const body = await response.json(); setError(typeof body.detail === 'string' ? body.detail : 'Check the calendar dates.'); setSaving(false); return; }
    setOpen(false); setTerms(blankTerms()); setSaving(false); await load();
  }

  async function transition(period: AcademicPeriod, status: 'open'|'closing'|'closed', confirmed = false) {
    if (period.status === 'closing' && status === 'closed' && !confirmed) { await reviewClose(period); return false; }
    let reason: string | undefined;
    if (period.status === 'closed') { reason = window.prompt('Why is this closed period being reopened?')?.trim(); if (!reason) return; }
    const response = await fetch(`${API}/api/v1/academic-periods/${period.id}/transition`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, reason }) });
    const body = await response.json() as TransitionResult & {detail?:string|{message?:string}};
    if (!response.ok) { setError(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? 'Unable to change period status.'); return false; }
    clearPeriods(); await selectPeriod(period.id); await load();
    return body;
  }

  async function reviewClose(period: AcademicPeriod) {
    setClosingPeriod(period); setReadiness(null); setCheckingClose(true); setError('');
    const response = await fetch(`${API}/api/v1/academic-periods/${period.id}/close-readiness`, {cache:'no-store'});
    if (!response.ok) { const body = await response.json().catch(() => null); setError(typeof body?.detail === 'string' ? body.detail : 'The pre-close checklist could not be loaded.'); setClosingPeriod(null); setCheckingClose(false); return; }
    setReadiness(await response.json()); setCheckingClose(false);
  }

  async function closeReviewedPeriod() {
    if (!closingPeriod || !readiness?.ready_to_close) return;
    setCheckingClose(true);
    const closed = await transition(closingPeriod, 'closed', true);
    setCheckingClose(false);
    if (closed) { setSummaryPeriod(closingPeriod); setCloseSummary(closed.close_summary ?? null); setClosingPeriod(null); setReadiness(null); }
  }

  async function viewCloseSummary(period: AcademicPeriod) {
    setSummaryPeriod(period); setCloseSummary(null); setCheckingClose(true); setError('');
    const response = await fetch(`${API}/api/v1/academic-periods/${period.id}/close-summary`, {cache:'no-store'});
    const body = await response.json().catch(() => null) as CloseSummary|{detail?:string}|null;
    if (!response.ok) { setError((body as {detail?:string}|null)?.detail ?? 'The closing summary could not be loaded.'); setSummaryPeriod(null); setCheckingClose(false); return; }
    setCloseSummary(body as CloseSummary); setCheckingClose(false);
  }

  async function reviewCarry(period: AcademicPeriod) {
    setCarrySource(period); setCarryPreview(null); setCarrySummary(null); setCheckingCarry(true); setError('');
    if (period.balance_carried_forward) {
      const response = await fetch(`${API}/api/v1/academic-periods/${period.id}/carry-forward`, {cache:'no-store'});
      const body = await response.json().catch(() => null);
      if (!response.ok) { setError(responseError(body,'The balance carry summary could not be loaded.')); setCarrySource(null); }
      else setCarrySummary(body as CarrySummary);
      setCheckingCarry(false); return;
    }
    const destination = nextConfiguredPeriod(period);
    if (!destination) { setError('Create the next academic period before carrying balances.'); setCarrySource(null); setCheckingCarry(false); return; }
    setCarryDestination(destination);
    const response = await fetch(`${API}/api/v1/academic-periods/${period.id}/carry-forward-preview?destination_period_id=${encodeURIComponent(destination.id)}`, {cache:'no-store'});
    const body = await response.json().catch(() => null);
    if (!response.ok) { setError(responseError(body,'The balance carry preview could not be prepared.')); setCarrySource(null); }
    else if (body.already_posted) setCarrySummary(body.carry_forward as CarrySummary);
    else setCarryPreview(body as CarryPreview);
    setCheckingCarry(false);
  }

  async function postCarry() {
    if (!carrySource || !carryDestination || !carryPreview?.ready_to_post) return;
    setPostingCarry(true); setError('');
    const response = await fetch(`${API}/api/v1/academic-periods/${carrySource.id}/carry-forward`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({destination_period_id:carryDestination.id,idempotency_key:`carry:${carrySource.id}:${carryDestination.id}`})});
    const body = await response.json().catch(() => null);
    if (!response.ok) { setError(responseError(body,'Balances could not be carried forward.')); setPostingCarry(false); return; }
    setCarrySummary(body as CarrySummary); setCarryPreview(null); setPostingCarry(false); clearPeriods(); await load();
  }

  function closeCarry() {
    setCarrySource(null); setCarryDestination(null); setCarryPreview(null); setCarrySummary(null); setCheckingCarry(false); setPostingCarry(false);
  }

  async function remove(period: AcademicPeriod) {
    if (!window.confirm(`Delete unused draft period “${period.name}”?`)) return;
    const response = await fetch(`${API}/api/v1/academic-periods/${period.id}`, { method: 'DELETE' });
    if (!response.ok) { const body = await response.json(); setError(body.detail ?? 'Unable to delete period.'); return; }
    await load();
  }

  async function correct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editing) return; setSaving(true);
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${API}/api/v1/academic-periods/${editing.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), opening_date: form.get('opening_date'), due_date: form.get('due_date'), closing_date: form.get('closing_date') }) });
    if (!response.ok) { const body = await response.json(); setError(body.detail ?? 'Unable to save correction.'); setSaving(false); return; }
    setEditing(null); setSaving(false); await load();
  }

  if (loading) return <div className="page-state"><LoaderCircle className="spin"/><h1>Loading academic calendar</h1><p>Checking operational and historical periods.</p></div>;
  return <>
    <PageHeader eyebrow="Control · Academic calendar" title="Academic periods" description="Open one working term, preserve closed history, and use the same period throughout the bursar workspace." actions={<button className="btn primary" onClick={() => setOpen(true)}><Plus size={16}/> New academic year</button>} />
    {error && <div className="notice period-error">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
    <section className="metric-grid period-metrics"><div className="metric-card"><CalendarDays/><span>Configured periods</span><strong>{periods.length}</strong><small>Across {new Set(periods.map(item => item.academic_year_id)).size} academic years</small></div><div className="metric-card"><CheckCircle2/><span>Operational period</span><strong>{operational?.name ?? 'Not opened'}</strong><small>{operational?.academic_year_name ?? 'Open a draft period to begin work'}</small></div><div className="metric-card"><LockKeyhole/><span>Closed history</span><strong>{periods.filter(item => item.status === 'closed').length}</strong><small>Protected against ordinary changes</small></div></section>
    <section className="panel period-register"><header className="panel-title"><div><span>Calendar register</span><h2>Terms and lifecycle</h2></div></header>{!periods.length ? <div className="empty-register"><CalendarDays/><strong>No academic year yet</strong><span>Create the school calendar before registering term activity.</span></div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Academic year</th><th>Period</th><th>Dates</th><th>Payment due</th><th>Status</th><th>Activity</th><th>Actions</th></tr></thead><tbody>{periods.map(period => <tr key={period.id}><td><strong>{period.academic_year_name}</strong><small>{period.academic_year}</small></td><td>{period.name}{period.balance_carried_into && <small>Opening balances carried in</small>}</td><td>{period.opening_date} — {period.closing_date}</td><td>{period.due_date}</td><td><span className={`status ${period.status}`}>{period.status}</span></td><td>{period.activity_count} records</td><td><div className="row-actions"><button title="Correct period" onClick={() => setEditing(period)} disabled={period.status === 'closed'}><Edit3 size={15}/></button>{period.status === 'draft' && <button onClick={() => transition(period, 'open')}>Open</button>}{period.status === 'open' && <button onClick={() => transition(period, 'closing')}>Start closing</button>}{period.status === 'closing' && <button onClick={() => transition(period, 'closed')}>Close</button>}{period.status === 'closed' && period.has_close_snapshot && <button onClick={() => reviewCarry(period)}>{period.balance_carried_forward ? 'View carry' : canManageCarry ? 'Carry balances' : 'Review carry'}</button>}{period.status === 'closed' && !period.has_close_snapshot && school?.role === 'owner' && <button onClick={() => transition(period, 'open')}>Reopen</button>}{period.status === 'draft' && <button title="Delete draft" onClick={() => remove(period)}><Trash2 size={15}/></button>}</div></td></tr>)}</tbody></table></div>}</section>
    {open && <div className="modal-backdrop"><section className="modal registration-modal"><header><div><h2>Create academic year</h2><p>Ugandan schools commonly use three terms. Keep, rename, add, or remove periods to match this school.</p></div><button onClick={() => setOpen(false)}><X size={20}/></button></header><form className="modal-form" onSubmit={createYear}><div className="form-grid"><label>Calendar year<input name="year" type="number" min="2000" max="2100" required /></label><label>Display name<input name="name" placeholder="2027 Academic Year" required /></label><label>Year opens<input name="start_date" type="date" required /></label><label>Year closes<input name="end_date" type="date" required /></label></div><div className="period-builder"><div className="form-section-title"><h3>School periods</h3><button type="button" className="btn compact" onClick={() => setTerms(items => [...items, {name:`Period ${items.length + 1}`,opening_date:'',due_date:'',closing_date:''}])}><Plus size={14}/> Add period</button></div>{terms.map((term, index) => <div className="period-draft" key={index}><strong>{index + 1}</strong><label>Name<input value={term.name} onChange={event => setTerms(items => items.map((item, i) => i === index ? {...item,name:event.target.value} : item))} required /></label><label>Opens<input type="date" value={term.opening_date} onChange={event => setTerms(items => items.map((item, i) => i === index ? {...item,opening_date:event.target.value} : item))} required /></label><label>Payment due<input type="date" value={term.due_date} onChange={event => setTerms(items => items.map((item, i) => i === index ? {...item,due_date:event.target.value} : item))} required /></label><label>Closes<input type="date" value={term.closing_date} onChange={event => setTerms(items => items.map((item, i) => i === index ? {...item,closing_date:event.target.value} : item))} required /></label>{terms.length > 1 && <button type="button" onClick={() => setTerms(items => items.filter((_, i) => i !== index))}><Trash2 size={15}/></button>}</div>)}</div><footer><button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button><button className="btn primary" disabled={saving}>{saving ? 'Creating…' : 'Create calendar'}</button></footer></form></section></div>}
    {editing && <div className="modal-backdrop"><section className="modal"><header><div><h2>Correct period</h2><p>Corrections are audited. Closed periods must be reopened first.</p></div><button onClick={() => setEditing(null)}><X size={20}/></button></header><form className="modal-form" onSubmit={correct}><label>Period name<input name="name" defaultValue={editing.name} required /></label><label>Opening date<input name="opening_date" type="date" defaultValue={editing.opening_date} required /></label><label>Payment due date<input name="due_date" type="date" defaultValue={editing.due_date} required /></label><label>Closing date<input name="closing_date" type="date" defaultValue={editing.closing_date} required /></label><footer><button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button><button className="btn primary" disabled={saving}>Save correction</button></footer></form></section></div>}
    {periods.some(period => period.has_close_snapshot) && <section className="panel close-archive"><header className="panel-title"><div><span>Immutable evidence</span><h2>Closing summaries</h2></div></header><div className="close-archive-list">{periods.filter(period => period.has_close_snapshot).map(period => <button key={period.id} onClick={() => viewCloseSummary(period)}><ShieldCheck/><span><strong>{period.name}</strong><small>{period.academic_year_name} · View frozen financial totals</small></span><ArrowUpRight size={15}/></button>)}</div></section>}
    {closingPeriod && <div className="modal-backdrop"><section className="modal close-review-modal">
      <header><div><h2>Pre-close controls</h2><p>{closingPeriod.name} can close only after every financial blocker is resolved.</p></div><button aria-label="Close checklist" onClick={() => {setClosingPeriod(null);setReadiness(null);}}><X size={20}/></button></header>
      {checkingClose && !readiness ? <div className="close-check-loading"><LoaderCircle className="spin"/><strong>Checking period controls</strong><span>Reviewing receipts, allocations, reconciliation and cash-up.</span></div> : readiness && <div className="close-review-body">
        <div className={`close-verdict ${readiness.ready_to_close ? 'ready' : 'blocked'}`}>{readiness.ready_to_close ? <ShieldCheck/> : <AlertTriangle/>}<div><strong>{readiness.ready_to_close ? 'Ready for controlled close' : `${readiness.blocker_count} control ${readiness.blocker_count === 1 ? 'blocker' : 'blockers'} remain`}</strong><span>{readiness.warning_count ? `${readiness.warning_count} approved difference must remain disclosed.` : 'All required controls have passed.'}</span></div><button className="btn compact" onClick={() => reviewClose(closingPeriod)} disabled={checkingClose}><RefreshCw size={14}/>Recheck</button></div>
        <div className="close-control-list">{readiness.controls.map(control => <article className={`close-control ${control.status}`} key={control.code}><div className="close-control-icon">{control.status === 'passed' ? <CheckCircle2/> : <AlertTriangle/>}</div><div><div className="close-control-title"><strong>{control.title}</strong><span>{control.status}</span></div><p>{control.detail}</p>{(control.count > 0 || Number(control.amount) !== 0) && <small>{control.count > 0 ? `${control.count.toLocaleString('en-UG')} item${control.count === 1 ? '' : 's'}` : ''}{control.count > 0 && Number(control.amount) !== 0 ? ' · ' : ''}{Number(control.amount) !== 0 ? `UGX ${Number(control.amount).toLocaleString('en-UG',{maximumFractionDigits:0})}` : ''}</small>}</div>{control.status !== 'passed' && <Link href={control.action_href} onClick={() => {setClosingPeriod(null);setReadiness(null);}}>Resolve <ArrowUpRight size={14}/></Link>}</article>)}</div>
      </div>}
      <footer><button className="btn" onClick={() => {setClosingPeriod(null);setReadiness(null);}}>Not now</button><button className="btn primary" disabled={!readiness?.ready_to_close || checkingClose} onClick={closeReviewedPeriod}>{checkingClose ? 'Closing…' : 'Close period'}</button></footer>
    </section></div>}
    {carrySource && <div className="modal-backdrop"><section className="modal carry-forward-modal"><header><div><h2>{carrySummary ? 'Balance carry record' : 'Carry balances forward'}</h2><p>{carrySource.name} · Controlled opening balances for the next configured period</p></div><button aria-label="Close balance carry" onClick={closeCarry}><X size={20}/></button></header>
      {checkingCarry ? <div className="close-check-loading"><LoaderCircle className="spin"/><strong>Preparing balance evidence</strong><span>Reading the immutable closing snapshot and checking the destination.</span></div> : carryPreview ? <div className="carry-forward-body">
        <div className={`carry-route ${carryPreview.ready_to_post ? 'ready' : 'blocked'}`}><div><span>Source</span><strong>{carryPreview.source_period.name}</strong><small>{carryPreview.source_period.academic_year_name}</small></div><ArrowRightLeft/><div><span>Destination</span><strong>{carryPreview.destination_period.name}</strong><small>{carryPreview.destination_period.academic_year_name}</small></div></div>
        <div className="close-summary-grid carry-totals"><div><span>Learners with balances</span><strong>{carryPreview.learner_count.toLocaleString('en-UG')}</strong></div><div><span>Debt carried</span><strong>{money(carryPreview.debt_total)}</strong><small>{carryPreview.debt_learner_count} learner accounts</small></div><div><span>Credit carried</span><strong>{money(carryPreview.credit_total)}</strong><small>{carryPreview.credit_learner_count} learner accounts</small></div></div>
        {carryPreview.ready_to_post ? <div className="carry-assurance"><ShieldCheck/><div><strong>Ready for controlled posting</strong><span>Each non-zero closing balance will become one traceable opening ledger entry. The source history remains unchanged.</span></div></div> : <div className="carry-assurance blocked"><AlertTriangle/><div><strong>Resolve conflicting opening balances</strong><span>{carryPreview.conflicting_opening_count} learner account(s) already have an explicit opening balance in {carryPreview.destination_period.name}.</span></div></div>}
        <div className="snapshot-hash"><span>Source evidence hash</span><code>{carryPreview.source_snapshot_hash}</code><small>The posted carry remains tied to this exact closing snapshot.</small></div>
      </div> : carrySummary && <div className="carry-forward-body">
        <div className="close-summary-seal"><ShieldCheck/><div><strong>Balances carried successfully</strong><span>{carrySummary.source_period_name} → {carrySummary.destination_period_name} · {new Date(carrySummary.posted_at).toLocaleString('en-UG')}</span></div></div>
        <div className="close-summary-grid carry-totals"><div><span>Learners posted</span><strong>{carrySummary.learner_count.toLocaleString('en-UG')}</strong></div><div><span>Debt carried</span><strong>{money(carrySummary.debt_total)}</strong></div><div><span>Credit carried</span><strong>{money(carrySummary.credit_total)}</strong></div></div>
        <div className="carry-line-register"><div className="carry-line-heading"><strong>Posted learner balances</strong><span>Signed opening amounts</span></div>{carrySummary.lines.length ? carrySummary.lines.map(line => <div className="carry-line" key={line.ledger_entry_id}><span><strong>{line.learner_name}</strong><small>{line.admission_no} · {line.balance_type}</small></span><strong className={line.balance_type}>{money(line.amount)}</strong></div>) : <div className="carry-line-empty">No non-zero balances required posting.</div>}</div>
        <div className="snapshot-hash"><span>Source evidence hash</span><code>{carrySummary.source_snapshot_hash}</code><small>Posted by {carrySummary.posted_by}. This record and its ledger entries are immutable.</small></div>
      </div>}
      <footer><button className="btn" onClick={closeCarry}>{carrySummary ? 'Done' : 'Not now'}</button>{carryPreview && canManageCarry && <button className="btn primary" disabled={!carryPreview.ready_to_post || postingCarry} onClick={postCarry}>{postingCarry ? 'Posting balances…' : `Post into ${carryPreview.destination_period.name}`}</button>}</footer>
    </section></div>}
    {summaryPeriod && <div className="modal-backdrop"><section className="modal close-summary-modal"><header><div><h2>Closing summary</h2><p>{summaryPeriod.name} · Immutable financial evidence</p></div><button aria-label="Close summary" onClick={() => {setSummaryPeriod(null);setCloseSummary(null);}}><X size={20}/></button></header>{checkingClose && !closeSummary ? <div className="close-check-loading"><LoaderCircle className="spin"/><strong>Loading closing evidence</strong></div> : closeSummary && <div className="close-summary-body"><div className="close-summary-seal"><ShieldCheck/><div><strong>Period closed successfully</strong><span>Snapshot version {closeSummary.snapshot_version} · {new Date(closeSummary.closed_at).toLocaleString('en-UG')}</span></div></div><div className="close-summary-grid"><div><span>Opening balance</span><strong>UGX {Number(closeSummary.opening_balance).toLocaleString('en-UG',{maximumFractionDigits:0})}</strong></div><div><span>Net assessed</span><strong>UGX {Number(closeSummary.net_assessed).toLocaleString('en-UG',{maximumFractionDigits:0})}</strong></div><div><span>Net collected</span><strong>UGX {Number(closeSummary.net_collected).toLocaleString('en-UG',{maximumFractionDigits:0})}</strong></div><div><span>Closing balance</span><strong>UGX {Number(closeSummary.closing_balance).toLocaleString('en-UG',{maximumFractionDigits:0})}</strong></div><div><span>Outstanding</span><strong>UGX {Number(closeSummary.outstanding).toLocaleString('en-UG',{maximumFractionDigits:0})}</strong></div><div><span>Learner credit</span><strong>UGX {Number(closeSummary.credit_balance).toLocaleString('en-UG',{maximumFractionDigits:0})}</strong></div></div><div className="close-summary-evidence"><div><span>Learners frozen</span><strong>{closeSummary.learner_count.toLocaleString('en-UG')}</strong></div><div><span>Approved warnings</span><strong>{closeSummary.warning_count}</strong></div><div><span>Closed by</span><strong>{closeSummary.closed_by}</strong></div></div><div className="snapshot-hash"><span>Evidence hash</span><code>{closeSummary.snapshot_hash}</code><small>This fingerprint identifies the exact learner rows, totals, and controls captured at close.</small></div></div>}<footer><button className="btn primary" onClick={() => {setSummaryPeriod(null);setCloseSummary(null);}}>Done</button></footer></section></div>}
  </>;
}
