'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Baby, BookOpen, Building2, Check, Network, School, ShieldCheck } from 'lucide-react';
import { MetricCard, PageHeader, SectionHeader } from '@/components/ui';
import { getPrimarySchool, setPrimarySchool, type School as SchoolRecord } from '@/lib/school';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Grade = { canonical_code: string; name: string };
type Template = { code: string; name: string; classes: Grade[] };
type RegisteredSchool = SchoolRecord & { emis_code?: string | null; programmes?: { programme_code:string; display_name:string }[] };

export default function InstitutionClient() {
  const router = useRouter();
  const [schools, setSchools] = useState<RegisteredSchool[]>([]), [templates, setTemplates] = useState<Template[]>([]);
  const [programmes, setProgrammes] = useState<string[]>([]), [grades, setGrades] = useState<string[]>([]);
  const [streamMode, setStreamMode] = useState<'none'|'single'|'multiple'>('none'), [streams, setStreams] = useState('');
  const [saving, setSaving] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    Promise.all([getPrimarySchool(), fetch(`${API}/api/v1/academic-structure/templates`).then(r => r.json())])
      .then(([school, templateRows]) => { setSchools([school]); setTemplates(templateRows); })
      .catch(() => setError('Institution setup service is unavailable.')).finally(() => setLoading(false));
  }, []);
  const selectedTemplates = useMemo(() => templates.filter(item => programmes.includes(item.code)), [templates, programmes]);
  const selectedGradeCount = grades.length;

  function toggleProgramme(template: Template, checked: boolean) {
    setProgrammes(current => checked ? [...current, template.code] : current.filter(code => code !== template.code));
    const codes = template.classes.map(item => item.canonical_code);
    setGrades(current => checked ? Array.from(new Set([...current, ...codes])) : current.filter(code => !codes.includes(code)));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(''); const form = new FormData(event.currentTarget);
    try {
      const defaultStreams = streamMode === 'none' ? [] : streamMode === 'single' ? [streams.trim()].filter(Boolean) : streams.split(',').map(value => value.trim()).filter(Boolean);
      const response = await fetch(`${API}/api/v1/schools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), district: form.get('district') || null, emis_code: form.get('emis_code') || null, programme_codes: programmes, canonical_codes: grades, default_streams: defaultStreams }) });
      const body = await response.json(); if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Institution could not be registered.');
      setPrimarySchool(body); router.push('/classes'); router.refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Institution could not be registered.'); setSaving(false); }
  }

  if (!loading && schools[0]) {
    const school = schools[0];
    return <><PageHeader eyebrow="Institution · Enterprise identity" title={school.organization_name ?? school.name} description={`${school.unit_name ?? 'Current section'} keeps separate bursar access and financial records under the institution identity.`} actions={<><Link className="btn" href="/onboarding?additional=1"><Network size={16}/>Add school section</Link><Link className="btn primary" href="/classes"><BookOpen size={16}/>Manage classes</Link></>}/>{error && <div className="form-error page-error">{error}</div>}<section className="metric-grid"><MetricCard icon={Building2} label="Institution" value={school.organization_name ?? school.name} note={school.district || 'District not set'}/><MetricCard icon={ShieldCheck} label="Current section" value={school.unit_name ?? school.name} note="Independent bursar workspace" tone="green"/><MetricCard icon={School} label="Programmes" value={String(school.programmes?.length ?? 0)} note={school.programmes?.map(item => item.display_name).join(' · ') || 'Class structure remains editable'} tone="blue"/><MetricCard icon={Network} label="Integration identity" value="UUID" note="Stable institution and section identifiers" tone="amber"/></section><section className="panel"><SectionHeader title="Academic structure policy" subtitle="Ugandan standard codes are retained separately from school-controlled class and stream names."/><div className="institution-policy"><p>Use <strong>Classes & streams</strong> to add new levels, rename classes, change their order, configure zero, one or many streams, or delete unused levels safely.</p><Link className="btn" href="/classes">Open academic structure</Link></div></section></>;
  }

  return <><PageHeader eyebrow="Institution · Guided registration" title="Register the school structure" description="Start from Uganda’s recognised stages, include only the levels currently offered, and keep every displayed name editable."/>{error && <div className="form-error page-error">{error}</div>}<form className="institution-form" onSubmit={submit}><section className="panel"><SectionHeader title="1. Institution identity" subtitle="These identifiers travel with finance and learner data shared through approved integrations."/><div className="institution-fields"><label>Registered school name<input name="name" required maxLength={160}/></label><label>District<input name="district" maxLength={80}/></label><label>EMIS code (if issued)<input name="emis_code" maxLength={40}/></label></div></section><section className="panel"><SectionHeader title="2. Programmes offered" subtitle="Choose all current programmes. Day care does not create artificial academic classes."/><div className="programme-options">{templates.map(template => <label key={template.code} className={programmes.includes(template.code) ? 'selected' : ''}><input type="checkbox" checked={programmes.includes(template.code)} onChange={event => toggleProgramme(template, event.target.checked)}/><span className="programme-icon">{template.code === 'day_care' ? <Baby/> : <School/>}</span><span><strong>{template.name}</strong><small>{template.classes.length ? template.classes.map(item => item.name).join(' · ') : 'Birth–3 care programme; no classes created.'}</small></span><Check className="selected-check"/></label>)}</div></section>{selectedTemplates.some(item => item.classes.length) && <section className="panel"><SectionHeader title="3. Exact classes offered" subtitle="A junior school may stop before P.7; a secondary school may stop at S.4 or continue through S.6."/><div className="grade-options">{selectedTemplates.flatMap(template => template.classes.map(grade => <label key={grade.canonical_code} className={grades.includes(grade.canonical_code) ? 'selected' : ''}><input type="checkbox" checked={grades.includes(grade.canonical_code)} onChange={event => setGrades(current => event.target.checked ? [...current, grade.canonical_code] : current.filter(code => code !== grade.canonical_code))}/><strong>{grade.name}</strong><small>{grade.canonical_code}</small></label>))}</div></section>}<section className="panel"><SectionHeader title="4. Initial stream structure" subtitle="Apply one choice to initial classes; each class remains independently editable afterward."/><div className="stream-setup"><label>Structure<select value={streamMode} onChange={event => setStreamMode(event.target.value as typeof streamMode)}><option value="none">No streams</option><option value="single">One named stream per class</option><option value="multiple">Multiple streams per class</option></select></label>{streamMode !== 'none' && <label>{streamMode === 'single' ? 'Stream name' : 'Stream names (comma separated)'}<input required value={streams} onChange={event => setStreams(event.target.value)} placeholder={streamMode === 'single' ? 'Main' : 'East, West'}/></label>}<div className="structure-summary"><strong>{programmes.length}</strong><span>programmes</span><strong>{selectedGradeCount}</strong><span>classes to create</span></div></div></section><footer className="registration-actions"><div><strong>Flexible by design</strong><span>Names and structure can evolve without changing stable record IDs.</span></div><button className="btn primary" disabled={saving || !programmes.length || (selectedTemplates.some(item => item.classes.length) && !grades.length)}>{saving ? 'Registering…' : 'Register institution'}</button></footer></form></>;
}
