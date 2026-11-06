'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, Layers3, Pencil, Plus, Trash2, Users, X } from 'lucide-react';
import { FilterSearch, MetricCard, PageHeader, RegisterFilters, SectionHeader } from '@/components/ui';
import { getPrimarySchool, type School } from '@/lib/school';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Stream = { id: string; name: string };
type AcademicClass = { id: string; name: string; level: string; canonical_code: string | null; sort_order: number; student_count: number; draft_fee_count: number; published_fee_count: number; draft_requirement_count: number; published_requirement_count: number; requirement_count: number; can_delete: boolean; delete_blocker: string | null; streams: Stream[] };
type Draft = { id?: string; name: string; level: string; canonical_code: string; sort_order: number; streamMode: 'none'|'single'|'multiple'; streams: string };
type Template = { code: string; name: string; classes: { canonical_code: string; name: string }[] };
const emptyDraft = (order: number): Draft => ({ name: '', level: 'primary', canonical_code: '', sort_order: order, streamMode: 'none', streams: '' });
const levelName: Record<string,string> = { pre_primary: 'Pre-primary / nursery', primary: 'Primary', lower_secondary: 'Lower secondary', upper_secondary: 'Advanced secondary', other: 'Other' };

export default function ClassesClient() {
  const [school, setSchool] = useState<School | null>(null);
  const [classes, setClasses] = useState<AcademicClass[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [templateStreams, setTemplateStreams] = useState('');
  const [loading, setLoading] = useState(true), [saving, setSaving] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [query, setQuery] = useState(''), [levelFilter, setLevelFilter] = useState('all'), [streamFilter, setStreamFilter] = useState('all');
  const loadClasses = useCallback(async (id: string) => {
    const response = await fetch(`${API}/api/v1/schools/${id}/classes`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Unable to load classes and streams.');
    setClasses(await response.json());
  }, []);

  useEffect(() => {
    Promise.all([
      getPrimarySchool(),
      fetch(`${API}/api/v1/academic-structure/templates`).then(response => response.json()),
    ]).then(([institution, rows]) => {
      setSchool(institution); setTemplates(rows); return loadClasses(institution.id);
    }).catch(() => setError('Unable to load the academic structure.')).finally(() => setLoading(false));
  }, [loadClasses]);

  const streamCount = useMemo(() => classes.reduce((total, item) => total + item.streams.length, 0), [classes]);
  const learnerCount = useMemo(() => classes.reduce((total, item) => total + item.student_count, 0), [classes]);
  const availableTemplates = templates.filter(item => item.classes.length);
  const visibleClasses = useMemo(() => {
    const term = query.trim().toLowerCase();
    return classes.filter(item => {
      const matchesQuery = !term || `${item.name} ${item.canonical_code ?? ''} ${item.streams.map(stream => stream.name).join(' ')}`.toLowerCase().includes(term);
      const matchesLevel = levelFilter === 'all' || item.level === levelFilter;
      const matchesStreams = streamFilter === 'all' || (streamFilter === 'with' ? item.streams.length > 0 : item.streams.length === 0);
      return matchesQuery && matchesLevel && matchesStreams;
    });
  }, [classes, levelFilter, query, streamFilter]);
  const classFiltersActive = Boolean(query || levelFilter !== 'all' || streamFilter !== 'all');

  function edit(item: AcademicClass) {
    const mode = item.streams.length === 0 ? 'none' : item.streams.length === 1 ? 'single' : 'multiple';
    setDraft({ id: item.id, name: item.name, level: item.level, canonical_code: item.canonical_code ?? '', sort_order: item.sort_order, streamMode: mode, streams: item.streams.map(stream => stream.name).join(', ') });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!draft || !school) return; setSaving(true); setError(''); setNotice('');
    const streams = draft.streamMode === 'none' ? [] : draft.streamMode === 'single' ? [draft.streams.trim()].filter(Boolean) : draft.streams.split(',').map(value => value.trim()).filter(Boolean);
    const payload = { name: draft.name, level: draft.level, canonical_code: draft.canonical_code || null, sort_order: draft.sort_order, streams };
    const url = draft.id ? `${API}/api/v1/classes/${draft.id}` : `${API}/api/v1/schools/${school.id}/classes`;
    try {
      const response = await fetch(url, { method: draft.id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!response.ok) { const body = await response.json(); throw new Error(typeof body.detail === 'string' ? body.detail : 'Class could not be saved.'); }
      setNotice(draft.id ? 'Class and stream structure updated.' : 'Class created.'); setDraft(null); await loadClasses(school.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Class could not be saved.'); } finally { setSaving(false); }
  }

  function openTemplate(template: Template) {
    setSelectedCodes(template.classes.map(item => item.canonical_code)); setTemplateStreams(''); setTemplateOpen(true);
  }

  async function applyTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!school || !selectedCodes.length) return; setSaving(true); setError('');
    const programme_codes = availableTemplates.filter(item => item.classes.some(row => selectedCodes.includes(row.canonical_code))).map(item => item.code);
    const streams = templateStreams.split(',').map(value => value.trim()).filter(Boolean);
    try {
      const response = await fetch(`${API}/api/v1/schools/${school.id}/classes/apply-template`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ programme_codes, canonical_codes: selectedCodes, streams }) });
      const body = await response.json(); if (!response.ok) throw new Error(body.detail ?? 'Structure could not be applied.');
      setTemplateOpen(false); setNotice(`${body.length} missing class${body.length === 1 ? '' : 'es'} added. Existing classes were preserved.`); await loadClasses(school.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Structure could not be applied.'); } finally { setSaving(false); }
  }

  async function remove(item: AcademicClass) {
    if (!school) return;
    if (!item.can_delete) { setError(item.delete_blocker ?? 'This class has records that must be preserved.'); return; }
    const drafts = item.draft_fee_count + item.draft_requirement_count;
    const cleanup = drafts ? ` Its ${drafts} unused draft billing record${drafts === 1 ? '' : 's'} will also be removed.` : '';
    if (!window.confirm(`Delete ${item.name}?${cleanup} This cannot be undone.`)) return;
    setError(''); setNotice(''); const response = await fetch(`${API}/api/v1/classes/${item.id}`, { method: 'DELETE' });
    if (!response.ok) { const body = await response.json(); setError(body.detail ?? 'Class could not be deleted.'); return; }
    setNotice(`${item.name} deleted.`); await loadClasses(school.id);
  }

  return <>
    <PageHeader eyebrow="Bursar · Academic billing structure" title="Classes & streams" description="This workspace contains only the classes managed by this section's bursar team. Names and streams remain editable." actions={<><button className="btn soft" disabled={!school} onClick={() => { setSelectedCodes([]); setTemplateOpen(true); }}><Layers3 size={16}/>Add standard levels</button><button className="btn primary" disabled={!school} onClick={() => setDraft(emptyDraft(classes.length + 1))}><Plus size={16}/>Add custom class</button></>}/>
    {error && <div className="form-error page-error">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}{notice && <div className="success-banner">{notice}<button onClick={() => setNotice('')}><X size={15}/></button></div>}
    <section className="metric-grid"><MetricCard icon={BookOpen} label="Configured classes" value={String(classes.length)} note="Editable academic levels"/><MetricCard icon={Layers3} label="Streams" value={String(streamCount)} note="Optional placement groups" tone="blue"/><MetricCard icon={Users} label="Placed learners" value={String(learnerCount)} note="Distinct enrolled learners" tone="green"/><MetricCard icon={BookOpen} label="Institution" value={school?.name ?? 'Not configured'} note="Active academic structure" tone="amber"/></section>
    <section className="panel structure-guide"><SectionHeader title="Uganda-aligned starting points" subtitle="Day care has no required classes; every other structure is selectable and remains fully editable."/><div className="template-strip">{templates.map(template => <article key={template.code}><div><strong>{template.name}</strong><span>{template.classes.length ? template.classes.map(item => item.name).join(' · ') : 'Birth–3 programme; register children without an academic class structure.'}</span></div>{template.classes.length > 0 && <button className="text-button" onClick={() => openTemplate(template)}>Choose classes</button>}</article>)}</div></section>
    <section className="panel class-panel">
      <SectionHeader title="School structure" subtitle="Canonical codes support data exchange; displayed names remain controlled by the school."/>
      <RegisterFilters shown={visibleClasses.length} total={classes.length} active={classFiltersActive} onReset={() => { setQuery(''); setLevelFilter('all'); setStreamFilter('all'); }}><FilterSearch value={query} onChange={setQuery} placeholder="Search class, code or stream"/><select className="select-control" aria-label="Education programme" value={levelFilter} onChange={event => setLevelFilter(event.target.value)}><option value="all">All programmes</option>{Object.entries(levelName).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select className="select-control" aria-label="Stream setup" value={streamFilter} onChange={event => setStreamFilter(event.target.value)}><option value="all">Any stream setup</option><option value="with">With streams</option><option value="none">Without streams</option></select></RegisterFilters>
      <div className="class-grid">
        {visibleClasses.map(item => {
          const draftCount = item.draft_fee_count + item.draft_requirement_count;
          return <article className="class-card" key={item.id}>
            <header><div><span>{levelName[item.level] ?? item.level}</span><h3>{item.name}</h3><small>{item.canonical_code ? `Standard code ${item.canonical_code}` : 'Custom level'}</small></div><strong>{item.student_count}<small> learners</small></strong></header>
            <div className="stream-list">{item.streams.length ? item.streams.map(stream => <span key={stream.id}>{stream.name}</span>) : <em>No stream — learners belong directly to this class</em>}</div>
            {draftCount > 0 && item.can_delete && <small>{draftCount} unused draft billing record{draftCount === 1 ? '' : 's'} will be cleaned up if this class is deleted.</small>}
            {item.delete_blocker && <small>{item.delete_blocker}.</small>}
            <footer><span>Order {item.sort_order}</span><div><button className="text-button" onClick={() => edit(item)}><Pencil size={14}/>Edit</button><button className="text-button danger-link" disabled={!item.can_delete} title={item.delete_blocker ?? 'Delete unused class'} onClick={() => remove(item)}><Trash2 size={14}/>Delete</button></div></footer>
          </article>;
        })}
        {!loading && !visibleClasses.length && <div className="empty-register"><BookOpen/><strong>{classes.length ? 'No classes match these filters' : 'No classes configured'}</strong><span>{classes.length ? 'Reset or change the filters to see more classes.' : 'Day-care-only institutions can remain without classes; otherwise add a structure or custom class.'}</span></div>}
      </div>
    </section>
    {draft && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true"><header><div><h2>{draft.id ? 'Edit class' : 'Add custom class'}</h2><p>The displayed name is local; the optional standard code preserves meaning for connected systems.</p></div><button onClick={() => setDraft(null)}><X size={20}/></button></header><form className="modal-form" onSubmit={save}><label>Class name<input required maxLength={40} value={draft.name} onChange={event => setDraft({...draft, name: event.target.value})} placeholder="e.g. Primary Four or P.4"/></label><label>Education programme<select value={draft.level} onChange={event => setDraft({...draft, level: event.target.value})}><option value="pre_primary">Pre-primary / nursery</option><option value="primary">Primary</option><option value="lower_secondary">Lower secondary (S.1–S.4)</option><option value="upper_secondary">Advanced secondary (S.5–S.6)</option><option value="other">Custom / other</option></select></label><label>Standard code (optional)<input maxLength={32} value={draft.canonical_code} onChange={event => setDraft({...draft, canonical_code: event.target.value.toUpperCase()})} placeholder="P4, S2, TOP or a partner code"/></label><label>Display order<input required min={0} max={100} type="number" value={draft.sort_order} onChange={event => setDraft({...draft, sort_order: Number(event.target.value)})}/></label><label>Stream setup<select value={draft.streamMode} onChange={event => setDraft({...draft, streamMode: event.target.value as Draft['streamMode'], streams: event.target.value === 'none' ? '' : draft.streams})}><option value="none">No streams</option><option value="single">One named stream</option><option value="multiple">Multiple streams</option></select></label>{draft.streamMode !== 'none' && <label>{draft.streamMode === 'single' ? 'Stream name' : 'Stream names'}<input required value={draft.streams} onChange={event => setDraft({...draft, streams: event.target.value})} placeholder={draft.streamMode === 'single' ? 'e.g. Main' : 'e.g. East, West, Blue'}/><small className="field-help">Separate multiple streams with commas.</small></label>}<footer><button type="button" className="btn" onClick={() => setDraft(null)}>Cancel</button><button className="btn primary" disabled={saving}>{saving ? 'Saving…' : 'Save class'}</button></footer></form></section></div>}
    {templateOpen && <div className="modal-backdrop"><section className="modal registration-modal" role="dialog" aria-modal="true"><header><div><h2>Add an academic structure</h2><p>Select exactly the levels this school currently offers. You can add, rename, reorder or safely delete unused classes later.</p></div><button onClick={() => setTemplateOpen(false)}><X size={20}/></button></header><form className="modal-form" onSubmit={applyTemplate}><div className="template-selector">{availableTemplates.map(template => <fieldset key={template.code}><legend>{template.name}</legend>{template.classes.map(item => <label key={item.canonical_code}><input type="checkbox" checked={selectedCodes.includes(item.canonical_code)} onChange={event => setSelectedCodes(current => event.target.checked ? [...current, item.canonical_code] : current.filter(code => code !== item.canonical_code))}/><span><strong>{item.name}</strong><small>{item.canonical_code}</small></span></label>)}</fieldset>)}</div><label>Default streams for selected classes (optional)<input value={templateStreams} onChange={event => setTemplateStreams(event.target.value)} placeholder="Leave blank for no streams, or enter East, West"/></label><div className="notice"><strong>Safe application</strong><br/>Only missing standard classes are created. Existing names, learners, fees and streams are never overwritten.</div><footer><button type="button" className="btn" onClick={() => setTemplateOpen(false)}>Cancel</button><button className="btn primary" disabled={saving || !selectedCodes.length}>{saving ? 'Applying…' : 'Add selected classes'}</button></footer></form></section></div>}
  </>;
}
