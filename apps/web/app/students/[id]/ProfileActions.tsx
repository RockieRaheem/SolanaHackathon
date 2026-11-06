'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRightLeft, X } from 'lucide-react';
import { getSelectedPeriod } from '@/lib/period';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Group = { id: string; name: string; streams: { id: string; name: string }[] };

export default function ProfileActions({ studentId, schoolId, currentStatus }: { studentId: string; schoolId: string; currentStatus: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<Group[]>([]);
  const [classId, setClassId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (open) fetch(`${API}/api/v1/schools/${schoolId}/classes`).then(r => r.json()).then(setGroups); }, [open, schoolId]);
  const streams = useMemo(() => groups.find(group => group.id === classId)?.streams ?? [], [groups, classId]);
  async function changeStatus(value: string) {
    setError('');
    const response = await fetch(`${API}/api/v1/students/${studentId}/status`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: value }) });
    if (!response.ok) return setError('Status could not be updated.');
    router.refresh();
  }
  async function transfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true);
    const form = new FormData(event.currentTarget);
    const period = await getSelectedPeriod();
    const response = await fetch(`${API}/api/v1/students/${studentId}/transfer`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ class_id: classId, stream_id: form.get('stream_id') || null, period_id: period.id, academic_year: period.academic_year, term: period.sequence }) });
    if (response.ok) { const body = await response.json(); setOpen(false); setNotice(body.fee_assignment?.message ?? (body.fee_assignment?.status === 'assigned' ? `${body.fee_assignment.plan_name} was added to the learner account automatically.` : 'Placement updated.')); router.refresh(); } else { const body = await response.json(); setError(body.detail ?? 'Transfer failed.'); }
    setSaving(false);
  }
  return <>
    <div className="page-actions"><select className="select-control" aria-label="Learner status" value={currentStatus} onChange={event => changeStatus(event.target.value)}><option value="active">Active</option><option value="withdrawn">Withdrawn</option><option value="completed">Completed</option><option value="transferred">Transferred out</option><option value="archived">Archived</option></select><button className="btn primary" onClick={() => setOpen(true)}><ArrowRightLeft size={15}/>Move learner</button></div>
    {error && <div className="form-error">{error}</div>}
    {notice && <div className="success-banner">{notice}<button onClick={() => setNotice('')}><X size={15}/></button></div>}
    {open && <div className="modal-backdrop"><section className="modal"><header><div><h2>Move learner</h2><p>The placement is recorded in the selected period. A published general fee is applied automatically only when the learner has no other fee already posted for that period.</p></div><button onClick={() => setOpen(false)}><X size={20}/></button></header><form className="modal-form" onSubmit={transfer}><label>Class<select required value={classId} onChange={event => setClassId(event.target.value)}><option value="">Select class</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><label>Stream<select name="stream_id"><option value="">No stream</option>{streams.map(stream => <option key={stream.id} value={stream.id}>{stream.name}</option>)}</select></label><footer><button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button><button className="btn primary" disabled={saving}>{saving ? 'Moving…' : 'Confirm movement'}</button></footer></form></section></div>}
  </>;
}
