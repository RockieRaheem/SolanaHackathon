'use client';

import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, FileUp, ShieldCheck, Users } from 'lucide-react';
import { FilterSearch, MetricCard, PageHeader, RegisterFilters, SectionHeader } from '@/components/ui';
import { getPrimarySchool, type School } from '@/lib/school';
import { AcademicPeriod, getSelectedPeriod } from '@/lib/period';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Group = {id:string; name:string; streams:{id:string; name:string}[]}; type Row = Record<string,string>;
const required = ['first_name', 'last_name', 'gender', 'class', 'guardian_first_name', 'guardian_last_name', 'guardian_phone'];
function parseLine(line:string) { const cells:string[] = []; let value = '', quoted = false; for (let index = 0; index < line.length; index++) { const character = line[index]; if (character === '"' && line[index + 1] === '"') { value += '"'; index++; } else if (character === '"') quoted = !quoted; else if (character === ',' && !quoted) { cells.push(value.trim()); value = ''; } else value += character; } cells.push(value.trim()); return cells; }

export default function StudentImportClient() {
  const [schools, setSchools] = useState<School[]>([]), [schoolId, setSchoolId] = useState(''), [groups, setGroups] = useState<Group[]>([]), [rows, setRows] = useState<Row[]>([]);
  const [period, setPeriod] = useState<AcademicPeriod|null>(null);
  const [fileName, setFileName] = useState(''), [message, setMessage] = useState(''), [error, setError] = useState(''), [working, setWorking] = useState(false);
  const [query, setQuery] = useState(''), [classFilter, setClassFilter] = useState('all');
  useEffect(() => { Promise.all([getPrimarySchool(), getSelectedPeriod()]).then(([item, selected]) => { setSchools([item]); setSchoolId(item.id); setPeriod(selected); }).catch(() => setError('Unable to load institution or academic period.')); }, []);
  useEffect(() => { if (schoolId && period) fetch(`${API}/api/v1/schools/${schoolId}/classes`).then(response => response.json()).then(setGroups); }, [schoolId, period]);
  useEffect(() => { if (period) setRows(items => items.map(row => ({ ...row, academic_year: String(period.academic_year), term: String(period.sequence) }))); }, [period]);
  async function choose(event:ChangeEvent<HTMLInputElement>) { const file = event.target.files?.[0]; if (!file) return; setFileName(file.name); setError(''); setQuery(''); setClassFilter('all'); const lines = (await file.text()).split(/\r?\n/).filter(Boolean), headers = parseLine(lines[0]).map(value => value.toLowerCase()), missing = required.filter(value => !headers.includes(value)); if (missing.length) { setRows([]); return setError(`Missing columns: ${missing.join(', ')}`); } setRows(lines.slice(1).map(line => Object.fromEntries(parseLine(line).map((value, index) => [headers[index], value])))); }
  function payload(validateOnly:boolean) {
    if (!period) throw new Error('Select an academic period first.');
    return {validate_only:validateOnly, students:rows.map((row, index) => {
      const group = groups.find(item => item.name.toLowerCase() === row.class?.toLowerCase());
      if (!group) throw new Error(`Row ${index + 2}: class ${row.class} was not found`);
      const stream = group.streams.find(item => item.name.toLowerCase() === row.stream?.toLowerCase());
      if (row.stream && !stream) throw new Error(`Row ${index + 2}: stream ${row.stream} was not found`);
      return {school_id:schoolId, period_id:period.id, first_name:row.first_name, middle_name:row.middle_name || null, last_name:row.last_name, date_of_birth:row.date_of_birth || null, gender:row.gender?.toLowerCase(), learner_identification_number:row.lin || null, class_id:group.id, stream_id:stream?.id || null, academic_year:period.academic_year, term:period.sequence, boarding_status:row.boarding_status || 'day', nationality:row.nationality || 'Ugandan', previous_school:row.previous_school || null, special_needs:row.special_needs || null, guardians:[{first_name:row.guardian_first_name, last_name:row.guardian_last_name, relationship:row.guardian_relationship || 'guardian', phone:row.guardian_phone, email:row.guardian_email || null, is_primary:true}]};
    })};
  }
  async function submit(validateOnly:boolean) { setWorking(true); setError(''); setMessage(''); try { const response = await fetch(`${API}/api/v1/student-imports`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload(validateOnly))}), body = await response.json(); if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Import validation failed'); setMessage(validateOnly ? `${body.valid} rows validated. No records were saved.` : `${body.imported} learners imported successfully.`); if (!validateOnly) setRows([]); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Import failed'); } finally { setWorking(false); } }
  const classes = useMemo(() => Array.from(new Set(rows.map(row => row.class).filter(Boolean))).sort(), [rows]);
  const visibleRows = useMemo(() => { const term = query.trim().toLowerCase(); return rows.filter(row => (classFilter === 'all' || row.class === classFilter) && (!term || `${row.first_name} ${row.last_name} ${row.guardian_first_name} ${row.guardian_last_name} ${row.guardian_phone}`.toLowerCase().includes(term))); }, [classFilter, query, rows]);

  return <><PageHeader eyebrow="Bursar · Opening accounts" title="Import learners" description="Validate placement and guardian details before creating learner accounts atomically. Billing stays in draft until reviewed and published." actions={<label className="btn primary"><FileUp size={16}/>Choose CSV<input hidden type="file" accept=".csv,text/csv" onChange={choose}/></label>}/>
    {error && <div className="form-error page-error">{error}</div>}{message && <div className="success-banner"><CheckCircle2 size={16}/>{message}</div>}
    <section className="metric-grid"><MetricCard icon={FileUp} label="Selected file" value={fileName || 'None'} note="CSV format"/><MetricCard icon={Users} label="Rows detected" value={String(rows.length)} note="Maximum 500 per batch" tone="blue"/><MetricCard icon={ShieldCheck} label="Write policy" value="Atomic" note="All rows succeed or none are saved" tone="green"/><MetricCard icon={CheckCircle2} label="Institution" value={schools.find(item => item.id === schoolId)?.name ?? 'Loading'} note="Import destination" tone="amber"/></section>
    <section className="panel"><SectionHeader title="Import preview" subtitle="Required headers: first_name, last_name, gender, class, guardian_first_name, guardian_last_name, guardian_phone."/>{rows.length ? <><RegisterFilters shown={visibleRows.length} total={rows.length} active={Boolean(query || classFilter !== 'all')} onReset={() => { setQuery(''); setClassFilter('all'); }}><FilterSearch value={query} onChange={setQuery} placeholder="Search learner, guardian or phone"/><select className="select-control" aria-label="Import class" value={classFilter} onChange={event => setClassFilter(event.target.value)}><option value="all">All classes</option>{classes.map(value => <option key={value} value={value}>{value}</option>)}</select></RegisterFilters><div className="table-wrap"><table className="data-table"><thead><tr><th>Row</th><th>Learner</th><th>Class</th><th>Stream</th><th>Guardian</th><th>Phone</th></tr></thead><tbody>{visibleRows.slice(0, 50).map(row => { const sourceIndex = rows.indexOf(row); return <tr key={sourceIndex}><td>{sourceIndex + 2}</td><td>{row.first_name} {row.last_name}</td><td>{row.class}</td><td>{row.stream || '—'}</td><td>{row.guardian_first_name} {row.guardian_last_name}</td><td>{row.guardian_phone}</td></tr>; })}{!visibleRows.length && <tr><td colSpan={6}><div className="empty-register">No import rows match these filters.</div></td></tr>}</tbody></table></div><div className="page-actions import-actions"><button className="btn" disabled={working} onClick={() => submit(true)}>Validate all {rows.length}</button><button className="btn success" disabled={working} onClick={() => submit(false)}>Import all {rows.length} learners</button></div></> : <div className="empty-register"><FileUp/><strong>Select a CSV to begin</strong><span>The first row must contain column headers.</span></div>}</section>
  </>;
}
