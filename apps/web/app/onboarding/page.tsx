'use client';

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import { Baby, Check, GraduationCap, LoaderCircle, School, ShieldCheck } from 'lucide-react';
import { clearPrimarySchool, getPrimarySchool, SchoolLoadError, setPrimarySchool } from '@/lib/school';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Grade = {canonical_code:string; name:string};
type Template = {code:string; name:string; classes:Grade[]};
type Profile = {code:string; name:string; detail:string; programmes:string[]};
const profiles:Profile[] = [
  {code:'day_care', name:'Day care', detail:'Care programme without artificial academic classes', programmes:['day_care']},
  {code:'nursery', name:'Nursery / pre-primary', detail:'Baby, Middle and Top Class', programmes:['pre_primary']},
  {code:'primary', name:'Primary / junior school', detail:'Primary One through Primary Seven', programmes:['primary']},
  {code:'secondary_o', name:'O-Level secondary', detail:'Senior One through Senior Four', programmes:['lower_secondary']},
  {code:'secondary_full', name:'Full secondary', detail:'Senior One through Senior Six', programmes:['lower_secondary', 'upper_secondary']},
];

function OnboardingContent() {
  const router = useRouter();
  const additional = useSearchParams().get('additional') === '1';
  const [templates, setTemplates] = useState<Template[]>([]), [profile, setProfile] = useState(''), [programmes, setProgrammes] = useState<string[]>([]), [grades, setGrades] = useState<string[]>([]);
  const [streamMode, setStreamMode] = useState<'none'|'single'|'multiple'>('none'), [streams, setStreams] = useState('');
  const [loading, setLoading] = useState(true), [saving, setSaving] = useState(false), [error, setError] = useState('');
  const loadStructures = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (!additional) {
        await getPrimarySchool();
        router.replace('/dashboard');
        return;
      }
    } catch (reason) {
      if (reason instanceof SchoolLoadError && reason.status === 401) {
        clearPrimarySchool();
        router.replace('/login?error=session_expired&next=/onboarding');
        return;
      }
      if (reason instanceof SchoolLoadError && reason.status !== 403 && reason.status !== 404) {
        setError(reason.status === 503 ? 'The secure service is temporarily unavailable. Please try again.' : reason.message);
        setLoading(false);
        return;
      }
    }

    try {
      const response = await fetch(`${API}/api/v1/academic-structure/templates`);
      const body = await response.json().catch(() => null) as Template[] | { detail?: string } | null;
      if (response.status === 401) {
        clearPrimarySchool();
        router.replace('/login?error=session_expired&next=/onboarding');
        return;
      }
      if (!response.ok || !Array.isArray(body)) {
        throw new Error(body && !Array.isArray(body) ? body.detail : undefined);
      }
      setTemplates(body);
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : 'School structure options could not be loaded. Check your connection and try again.');
    } finally {
      setLoading(false);
    }
  }, [additional, router]);

  useEffect(() => { void loadStructures(); }, [loadStructures]);

  const selectedTemplates = useMemo(() => templates.filter(item => programmes.includes(item.code)), [programmes, templates]);
  const availableGrades = selectedTemplates.flatMap(item => item.classes);
  function chooseProfile(item:Profile) {
    setProfile(item.code); setProgrammes(item.programmes);
    setGrades(templates.filter(template => item.programmes.includes(template.code)).flatMap(template => template.classes.map(grade => grade.canonical_code)));
  }
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError('');
    const form = new FormData(event.currentTarget);
    const defaultStreams = streamMode === 'none' ? [] : streamMode === 'single' ? [streams.trim()].filter(Boolean) : streams.split(',').map(value => value.trim()).filter(Boolean);
    try {
      const response = await fetch(additional ? `${API}/api/v1/schools` : '/api/current-school', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:form.get('name'), district:form.get('district') || null, emis_code:form.get('emis_code') || null, programme_codes:programmes, canonical_codes:grades, default_streams:defaultStreams})});
      const body = await response.json();
      if (!response.ok) { const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail; throw new Error(detail || 'Institution setup could not be completed.'); }
      setPrimarySchool(body);
      if (additional) { window.location.assign(`/api/workspace/select?school_id=${body.id}&next=/dashboard`); return; }
      router.replace('/dashboard'); router.refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Institution setup could not be completed.'); setSaving(false); }
  }
  const classProgrammeSelected = selectedTemplates.some(item => item.classes.length);
  const structureValid = programmes.length > 0 && (!classProgrammeSelected || grades.length > 0);

  return <main className="onboarding-page"><header className="onboarding-header"><div><Image src="/harambeeone-logo.png" width={42} height={42} alt="HarambeeOne"/><span><strong>HarambeeOne</strong><small>Institution setup</small></span></div><span><ShieldCheck size={15}/>Secure bursar onboarding</span></header>
    <form className="onboarding-shell" onSubmit={submit}><section className="onboarding-intro"><span>{additional ? 'Institution settings · New section' : 'Account created · Step 2 of 2'}</span><h1>{additional ? 'Add another bursar workspace.' : 'Set up this bursar workspace.'}</h1><p>Choose the one campus section this bursar manages. Primary and secondary use separate workspaces and access, even when they belong to the same school.</p></section>
      {error && <div className="auth-message error" role="alert">{error}</div>}
      <section className="onboarding-section"><div className="onboarding-section-title"><span>1</span><div><h2>Managed section</h2><p>This workspace contains only the section and bursar team selected here.</p></div></div>{loading ? <div className="onboarding-loading"><LoaderCircle className="spin"/>Loading school structures…</div> : templates.length ? <div className="school-profile-grid">{profiles.map(item => <button type="button" key={item.code} className={profile === item.code ? 'selected' : ''} onClick={() => chooseProfile(item)}><span>{item.code === 'day_care' ? <Baby/> : item.code.includes('secondary') ? <GraduationCap/> : <School/>}</span><div><strong>{item.name}</strong><small>{item.detail}</small></div><Check/></button>)}</div> : <div className="onboarding-retry"><p>We could not securely load the school structure catalogue.</p><button type="button" className="btn primary" onClick={() => void loadStructures()}>Try again</button><button type="button" className="btn" onClick={() => router.replace('/login')}>Return to sign in</button></div>}</section>
      {profile && <><section className="onboarding-section"><div className="onboarding-section-title"><span>2</span><div><h2>Classes in this section</h2><p>Select only the classes currently managed here. Additional sections are created as separate workspaces.</p></div></div>{availableGrades.length > 0 && <div className="onboarding-grades">{availableGrades.map(grade => <label key={grade.canonical_code} className={grades.includes(grade.canonical_code) ? 'selected' : ''}><input type="checkbox" checked={grades.includes(grade.canonical_code)} onChange={event => setGrades(current => event.target.checked ? [...current, grade.canonical_code] : current.filter(code => code !== grade.canonical_code))}/><strong>{grade.name}</strong><small>{grade.canonical_code}</small></label>)}</div>}</section>
        <section className="onboarding-section"><div className="onboarding-section-title"><span>3</span><div><h2>Institution details</h2><p>These details identify the school throughout every bursar register and report.</p></div></div><div className="onboarding-fields"><label>Registered school name<input name="name" required maxLength={160} placeholder="e.g. Kampala Junior School"/></label><label>District<input name="district" maxLength={80} placeholder="e.g. Kampala"/></label><label>EMIS code <small>Optional if not yet issued</small><input name="emis_code" maxLength={40}/></label><label>Initial stream structure<select value={streamMode} onChange={event => setStreamMode(event.target.value as typeof streamMode)}><option value="none">No streams</option><option value="single">One named stream per class</option><option value="multiple">Multiple streams per class</option></select></label>{streamMode !== 'none' && <label className="wide">{streamMode === 'single' ? 'Stream name' : 'Stream names'}<input required value={streams} onChange={event => setStreams(event.target.value)} placeholder={streamMode === 'single' ? 'Main' : 'East, West, Blue'}/><small>{streamMode === 'multiple' ? 'Separate stream names with commas.' : 'This can be changed independently for each class later.'}</small></label>}</div></section>
        <footer className="onboarding-actions"><div><strong>{programmes.length} programme{programmes.length === 1 ? '' : 's'} · {grades.length} class{grades.length === 1 ? '' : 'es'}</strong><span>Every page will use this institution and its selected structure.</span></div><button className="auth-submit" disabled={saving || !structureValid}>{saving && <LoaderCircle className="spin" size={18}/>}Create school workspace</button></footer></>}
    </form>
  </main>;
}

export default function OnboardingPage() {
  return <Suspense fallback={<main className="onboarding-page"/>}><OnboardingContent/></Suspense>;
}
