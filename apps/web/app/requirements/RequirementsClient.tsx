'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  ClipboardCheck,
  PackageCheck,
  Plus,
  X,
} from 'lucide-react';
import { FilterSearch, PageHeader, RegisterFilters, SectionHeader, Status } from '@/components/ui';
import { getPrimarySchool, type School } from '@/lib/school';
import { AcademicPeriod, getSelectedPeriod } from '@/lib/period';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';

type Group = { id: string; name: string; canonical_code: string | null; student_count: number; streams:{id:string;name:string}[] };
type Student = {id:string;full_name:string;admission_no:string;class_name:string;stream_name:string|null};
type Requirement = {
  id: string;
  name: string;
  code: string;
  requirement_type: 'payment' | 'school_item' | 'bring_item' | 'document';
  description: string | null;
  academic_year: number;
  term: number;
  amount: string;
  quantity: string;
  unit: string;
  due_date: string | null;
  is_mandatory: boolean;
  status: 'draft' | 'published';
  selected_learner_count: number;
  classes: { id: string; name: string }[];
  assigned_count: number;
  completed_count: number;
  paid_amount: string;
};
type Assignment = {
  id: string;
  student_name: string;
  admission_no: string;
  class_name: string;
  requirement_name: string;
  requirement_type: Requirement['requirement_type'];
  expected_amount: string;
  paid_amount: string;
  outstanding_amount: string;
  expected_quantity: string;
  fulfilled_quantity: string;
  unit: string;
  status: string;
  due_date: string | null;
};

const typeLabels = {
  payment: 'Payable service',
  school_item: 'School-issued item',
  bring_item: 'Item brought to school',
  document: 'Document or evidence',
};

function statusTone(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (['complete', 'issued', 'received', 'waived'].includes(value)) return 'success';
  if (['partially_paid', 'partially_issued', 'partially_received'].includes(value)) return 'warning';
  if (value === 'paid') return 'info';
  return 'danger';
}

export default function RequirementsClient() {
  const searchParams = useSearchParams();
  const [school, setSchool] = useState<School | null>(null);
  const [period, setPeriod] = useState<AcademicPeriod | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [requirementType, setRequirementType] = useState<Requirement['requirement_type']>('school_item');
  const [mandatory, setMandatory] = useState(true);
  const [targetMode, setTargetMode] = useState<'cohort'|'selected'>('cohort');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [catalogueSearch, setCatalogueSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [selectedClassId, setSelectedClassId] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadRequirements = useCallback(async (schoolId: string, periodId: string) => {
    const response = await fetch(`${API}/api/v1/requirements?school_id=${schoolId}&period_id=${periodId}`);
    if (!response.ok) throw new Error('Requirements could not be loaded.');
    const rows: Requirement[] = await response.json();
    setRequirements(rows);
    setSelectedId(current => current || rows[0]?.id || '');
  }, []);

  const loadAssignments = useCallback(async (schoolId: string, periodId: string, requirementId: string) => {
    if (!requirementId) {
      setAssignments([]);
      return;
    }
    const response = await fetch(
      `${API}/api/v1/requirement-assignments?school_id=${schoolId}&period_id=${periodId}&requirement_id=${requirementId}`,
    );
    if (!response.ok) throw new Error('Learner requirement register could not be loaded.');
    setAssignments(await response.json());
  }, []);

  useEffect(() => {
    Promise.all([getPrimarySchool(), getSelectedPeriod()])
      .then(async ([item, selected]) => {
        setSchool(item);
        setPeriod(selected);
        const [classResponse,studentResponse] = await Promise.all([fetch(`${API}/api/v1/schools/${item.id}/classes`),fetch(`${API}/api/v1/students?school_id=${item.id}&period_id=${selected.id}`)]);
        if (!classResponse.ok||!studentResponse.ok) throw new Error();
        const classRows: Group[] = await classResponse.json();
        setGroups(classRows);
        const requestedClass = searchParams.get('class');
        const initialClass = classRows.some(group => group.id === requestedClass) ? requestedClass! : classRows[0]?.id ?? '';
        setSelectedClassId(initialClass);
        if (searchParams.get('create') === '1' && initialClass) setCreateOpen(true);
        setStudents((await studentResponse.json()).items);
        await loadRequirements(item.id, selected.id);
      })
      .catch(() => setError('Requirements service is unavailable.'));
  }, [loadRequirements, searchParams]);

  useEffect(() => {
    if (school && period && selectedId) {
      loadAssignments(school.id, period.id, selectedId).catch(reason =>
        setError(reason instanceof Error ? reason.message : 'Requirements could not be loaded.'),
      );
    }
  }, [loadAssignments, period, school, selectedId]);

  const selectedGroup = groups.find(group => group.id === selectedClassId) ?? null;
  const classStudents = students.filter(student => student.class_name === selectedGroup?.name);
  const selected = requirements.find(item => item.id === selectedId) ?? null;
  const filteredRequirements = useMemo(() => {
    const term = catalogueSearch.trim().toLowerCase();
    return requirements.filter(item => {
      const matchesSearch = !term || (item.name+' '+item.code+' '+(item.description ?? '')).toLowerCase().includes(term);
      const matchesType = typeFilter === 'all' || item.requirement_type === typeFilter;
      const matchesClass = item.classes.some(value => value.id === selectedClassId);
      return matchesSearch && matchesType && matchesClass;
    });
  }, [catalogueSearch, requirements, selectedClassId, typeFilter]);
  const catalogueFiltersActive = Boolean(catalogueSearch || typeFilter !== 'all');
  useEffect(() => {
    const classRows = requirements.filter(item => item.classes.some(value => value.id === selectedClassId));
    setSelectedId(current => classRows.some(item => item.id === current) ? current : classRows[0]?.id ?? '');
  }, [requirements, selectedClassId]);
  const filteredAssignments = useMemo(() => {
    const term = search.trim().toLowerCase();
    return assignments.filter(item => {
      const matchesSearch = !term || `${item.student_name} ${item.admission_no} ${item.class_name}`.toLowerCase().includes(term);
      const complete = ['complete', 'issued', 'received', 'waived'].includes(item.status);
      const matchesFilter = filter === 'all' || (filter === 'complete' ? complete : !complete);
      return matchesSearch && matchesFilter;
    });
  }, [assignments, filter, search]);

  async function createRequirement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!school || !period || !selectedGroup) return;
    setSaving(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const name = String(form.get('name') || '').trim();
    const code = [selectedGroup.canonical_code || selectedGroup.name, name, 'T'+period.sequence].join('-').replace(/[^A-Za-z0-9_-]/g, '').toUpperCase().slice(0, 20);
    const payload = {
      school_id: school.id,
      period_id: period.id,
      name,
      code,
      requirement_type: form.get('requirement_type'),
      description: form.get('description') || null,
      academic_year: period.academic_year,
      term: period.sequence,
      amount: ['payment', 'school_item'].includes(String(form.get('requirement_type')))
        ? Number(form.get('amount'))
        : 0,
      quantity: Number(form.get('quantity')),
      unit: form.get('unit') || (requirementType === 'document' ? 'document' : 'item'),
      due_date: form.get('due_date') || null,
      is_mandatory: form.get('is_mandatory') === 'on',
      class_ids: [selectedClassId],
      stream_id: form.get('stream_id') || null,
      boarding_status: form.get('boarding_status') || null,
      student_ids: targetMode === 'selected' ? form.getAll('student_ids') : [],
    };
    try {
      const response = await fetch(`${API}/api/v1/requirements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
        throw new Error(detail || 'Requirement could not be created.');
      }
      setCreateOpen(false);
      setSelectedId(body.id);
      setNotice('Draft requirement created. Review and publish it from Fees & billing.');
      await loadRequirements(school.id, period.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Requirement could not be created.');
    } finally {
      setSaving(false);
    }
  }

  async function fulfil(item: Assignment) {
    const remaining = Number(item.expected_quantity) - Number(item.fulfilled_quantity);
    const action = item.requirement_type === 'school_item' ? 'issue' : 'receive';
    if (!window.confirm(`Confirm ${action} of ${remaining} ${item.unit} for ${item.student_name}?`)) return;
    setError('');
    const response = await fetch(`${API}/api/v1/requirement-assignments/${item.id}/fulfil`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantity: remaining, note: `${action} recorded from requirement register` }),
    });
    const body = await response.json();
    if (!response.ok) {
      setError(body.detail || 'Fulfilment could not be recorded.');
      return;
    }
    setNotice(`${item.requirement_name} marked ${action === 'issue' ? 'issued' : 'received'} for ${item.student_name}.`);
    if (school && period && selected) {
      await Promise.all([loadRequirements(school.id, period.id), loadAssignments(school.id, period.id, selected.id)]);
    }
  }

  async function removeDraftRequirement() {
    if (!selected || selected.status !== 'draft' || !window.confirm(`Remove the draft requirement "${selected.name}"?`)) return;
    setError('');
    const response = await fetch(`${API}/api/v1/requirements/${selected.id}`, { method: 'DELETE' });
    if (!response.ok) {
      const body = await response.json();
      setError(body.detail || 'Requirement could not be removed.');
      return;
    }
    setSelectedId('');
    setNotice('Draft requirement removed.');
    if (school && period) await loadRequirements(school.id, period.id);
  }

  const classRequirements = requirements.filter(item => item.classes.some(value => value.id === selectedClassId));
  const totalAssignments = classRequirements.reduce((sum, item) => sum + item.assigned_count, 0);
  const totalComplete = classRequirements.reduce((sum, item) => sum + item.completed_count, 0);
  return <>
    <PageHeader
      eyebrow="Bursar · Class obligations"
      title="Requirements"
      description="Choose a class, add the items or services its learners need, then publish them with the class fee."
      actions={<button className="btn primary" disabled={!selectedClassId} onClick={() => setCreateOpen(true)}><Plus size={16}/>Add to {selectedGroup?.name??'class'}</button>}
    />
    {error && <div className="form-error page-error">{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
    {notice && <div className="success-banner">{notice}<button onClick={() => setNotice('')}><X size={15}/></button></div>}

    <section className="panel class-billing-workspace">
      <SectionHeader title="Choose a class" subtitle="The catalogue and new requirements below stay scoped to this class." action={<Link className="text-button" href="/fees">Review billing preview</Link>}/>
      <div className="class-scope-list" role="tablist" aria-label="Classes">
        {groups.map(group=>{const count=requirements.filter(item=>item.classes.some(value=>value.id===group.id)).length;return <button type="button" role="tab" aria-selected={selectedClassId===group.id} className={selectedClassId===group.id?'class-scope-card active':'class-scope-card'} key={group.id} onClick={()=>setSelectedClassId(group.id)}><strong>{group.name}</strong><span>{group.student_count} learner{group.student_count===1?'':'s'}</span><small>{count} requirement{count===1?'':'s'}</small></button>})}
      </div>
      {selectedGroup&&<div className="compact-class-summary"><strong>{selectedGroup.name}</strong><span>{classRequirements.length} configured</span><span>{totalAssignments} learner assignments</span><span>{totalComplete} completed</span><button className="btn primary" onClick={()=>setCreateOpen(true)}><Plus size={14}/>Add requirement</button></div>}
    </section>

    <section className="panel requirement-catalogue">
      <SectionHeader title={(selectedGroup?.name??'Class')+' requirements'} subtitle="Select a row to open its learner fulfilment register." />
      <RegisterFilters shown={filteredRequirements.length} total={classRequirements.length} active={catalogueFiltersActive} onReset={() => { setCatalogueSearch(''); setTypeFilter('all'); }}>
        <FilterSearch value={catalogueSearch} onChange={setCatalogueSearch} placeholder="Search requirement or code" />
        <select className="select-control" aria-label="Requirement type" value={typeFilter} onChange={event => setTypeFilter(event.target.value)}><option value="all">All types</option>{Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      </RegisterFilters>
      <div className="table-wrap">
        <table className="data-table requirements-table">
          <thead><tr><th>Requirement</th><th>Amount / quantity</th><th>Coverage</th></tr></thead>
          <tbody>
            {filteredRequirements.map(item => {
              const coverage = item.assigned_count ? Math.round(item.completed_count / item.assigned_count * 100) : 0;
              return <tr key={item.id} className={selectedId === item.id ? 'selected-row' : ''} onClick={() => setSelectedId(item.id)}>
                <td className="entity"><strong>{item.name}</strong><small>{item.code} · {typeLabels[item.requirement_type]} · {item.is_mandatory ? 'Required' : 'Optional'} · {item.status}</small></td>

                <td className="entity"><strong>{Number(item.amount) > 0 ? `UGX ${Number(item.amount).toLocaleString()}` : 'No cash payment'}</strong><small>{Number(item.quantity)} {item.unit}</small></td>
                <td><div className="coverage-cell"><span>{item.completed_count}/{item.assigned_count}</span><div className="progress"><i style={{ width: `${coverage}%` }} /></div></div></td>
              </tr>;
            })}
            {!filteredRequirements.length && <tr><td colSpan={3}><div className="empty-register"><ClipboardCheck/><strong>{classRequirements.length ? 'No requirements match these filters' : 'No requirements configured for this class'}</strong><span>{classRequirements.length ? 'Reset or change the filters to see more requirements.' : 'Add the first fee-related item, service or document for this class.'}</span></div></td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    {selected && <section className="panel requirement-register">
      <SectionHeader
        title={`${selected.name} · learner register`}
        subtitle={`${selected.classes.map(item => item.name).join(', ')} · ${selected.academic_year} Term ${selected.term}`}
        action={selected.status === 'draft' ? <div className="row-actions"><button className="text-button" onClick={removeDraftRequirement}>Remove draft</button><Link className="text-button" href="/fees">Preview and publish billing</Link></div> : undefined}
      />
      <RegisterFilters shown={filteredAssignments.length} total={assignments.length} active={Boolean(search || filter !== 'all')} onReset={() => { setSearch(''); setFilter('all'); }}>
        <FilterSearch value={search} onChange={setSearch} placeholder="Search learner, admission number or class" />
        <select className="select-control" aria-label="Fulfilment status" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All statuses</option><option value="open">Needs attention</option><option value="complete">Completed</option></select>
      </RegisterFilters>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Learner</th><th>Class</th><th>Payment</th><th>Handover</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>{filteredAssignments.map(item => {
            const canFulfil = item.requirement_type !== 'payment' && !['issued', 'received'].includes(item.status);
            return <tr key={item.id}>
              <td className="entity"><strong>{item.student_name}</strong><small>{item.admission_no}</small></td>
              <td>{item.class_name}</td>
              <td className="entity"><strong>{Number(item.expected_amount) ? `UGX ${Number(item.paid_amount).toLocaleString()} / ${Number(item.expected_amount).toLocaleString()}` : 'Not payable'}</strong><small>{Number(item.outstanding_amount) > 0 ? `UGX ${Number(item.outstanding_amount).toLocaleString()} outstanding` : 'No payment balance'}</small></td>
              <td>{Number(item.fulfilled_quantity)} / {Number(item.expected_quantity)} {item.unit}</td>
              <td><Status tone={statusTone(item.status)}>{item.status.replaceAll('_', ' ')}</Status></td>
              <td>{canFulfil ? <button className="btn compact" onClick={() => fulfil(item)}><PackageCheck size={14}/>{item.requirement_type === 'school_item' ? 'Issue' : 'Receive'}</button> : <span className="muted-action">—</span>}</td>
            </tr>;
          })}{!filteredAssignments.length && <tr><td colSpan={6}><div className="empty-register"><PackageCheck/><strong>No learners match this view</strong><span>Synchronize the requirement or change the current filters.</span></div></td></tr>}</tbody>
        </table>
      </div>
    </section>}

    {createOpen && selectedGroup && <div className="modal-backdrop"><section className="modal registration-modal" role="dialog" aria-modal="true">
      <header><div><h2>Add requirement to {selectedGroup.name}</h2><p>Define the obligation once. It will follow every eligible learner in this class when billing is published.</p></div><button onClick={() => setCreateOpen(false)}><X size={20}/></button></header>
      <form className="modal-form" onSubmit={createRequirement}>
        <div className="class-form-context"><span>Applying to</span><strong>{selectedGroup.name}</strong><small>{selectedGroup.student_count} active learner{selectedGroup.student_count===1?'':'s'} · {period?.name}</small></div>
        <div className="form-section"><h3>What is required?</h3><div className="form-grid">
          <label>Name<input name="name" required autoFocus placeholder="Candidate T-shirt" /></label>
          <label>How it is handled<select name="requirement_type" value={requirementType} onChange={event => setRequirementType(event.target.value as Requirement['requirement_type'])}><option value="school_item">Paid, then issued by school</option><option value="payment">Payment or service only</option><option value="bring_item">Parent brings an item</option><option value="document">Parent submits a document</option></select></label>
          <label>Due date<input name="due_date" type="date" defaultValue={period?.due_date??''}/></label>
          {['payment', 'school_item'].includes(requirementType) && <label>Amount per learner (UGX)<input name="amount" type="number" min="1" step="1" required /></label>}
          <label>Quantity per learner<input name="quantity" type="number" min="0.01" step="0.01" defaultValue="1" required /></label>
          <label>Unit<input key={requirementType} name="unit" defaultValue={requirementType === 'document' ? 'document' : 'item'} required placeholder="item, set, ream" /></label>
        </div><label className="long-label">Instructions <span className="optional-label">Optional</span><textarea name="description" placeholder="Size, colour, acceptable document or handover instructions" /></label><label className="check-label"><input name="is_mandatory" type="checkbox" checked={mandatory} onChange={event=>{setMandatory(event.target.checked);setTargetMode(event.target.checked?'cohort':'selected')}} /> Assign to every eligible learner in {selectedGroup.name}</label></div>
        <details className="advanced-options"><summary>Advanced targeting <span>Stream, residence or selected learners</span></summary><div className="form-grid"><label>Target mode<select value={targetMode} onChange={event=>{const mode=event.target.value as 'cohort'|'selected';setTargetMode(mode);setMandatory(mode==='cohort')}}><option value="cohort" disabled={!mandatory}>Every matching learner</option><option value="selected">Selected learners only</option></select></label><label>Stream<select name="stream_id"><option value="">All streams</option>{selectedGroup.streams.map(stream=><option key={stream.id} value={stream.id}>{stream.name}</option>)}</select></label><label>Residence<select name="boarding_status"><option value="">All residence types</option><option value="day">Day</option><option value="boarding">Boarding</option><option value="half_boarding">Half boarding</option></select></label></div>{targetMode==='selected'&&<div className="class-choice-grid learner-choice-grid">{classStudents.map(student=><label key={student.id}><input type="checkbox" name="student_ids" value={student.id}/><span><strong>{student.full_name}</strong><small>{student.admission_no}{student.stream_name?' · '+student.stream_name:''}</small></span></label>)}{!classStudents.length&&<p className="form-help">No active learners are placed in this class.</p>}</div>}</details>
        <footer><button type="button" className="btn" onClick={() => setCreateOpen(false)}>Cancel</button><button className="btn primary" disabled={saving}>{saving ? 'Creating…' : 'Save draft requirement'}</button></footer>
      </form>
    </section></div>}
  </>;
}
