import Link from 'next/link';
import { ArrowLeft, ShieldCheck } from 'lucide-react';
import { PageHeader, SectionHeader } from '@/components/ui';
import ProfileActions from './ProfileActions';
import ProfileEditor from './ProfileEditor';
import LearnerAccount from './LearnerAccount';
import { authorizedBackendFetch } from '@/lib/api/server';

export default async function StudentProfilePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await authorizedBackendFetch(`/api/v1/students/${id}`).catch(() => null);
  if (!response?.ok) return <div className="page-state"><h1>Learner unavailable</h1><p>The finance service could not load this learner account.</p><Link className="btn" href="/students">Back to registry</Link></div>;
  const profile = await response.json();
  const name = [profile.first_name, profile.middle_name, profile.last_name].filter(Boolean).join(' ');
  return <><PageHeader eyebrow="Bursar · Learner account" title={name} description={`${profile.admission_no} · ${profile.status} · ${profile.boarding_status.replace('_',' ')} learner`} actions={<><Link className="btn" href="/students"><ArrowLeft size={15}/>Registry</Link><ProfileEditor studentId={id} profile={profile}/><ProfileActions studentId={id} schoolId={profile.school_id} currentStatus={profile.status}/></>}/>
    <LearnerAccount studentId={id}/>
    <section className="panel guardian-register"><SectionHeader title="Guardians" subtitle="Authorized family contacts; statements use only a contact permitted to receive them."/><div className="attention-list">{profile.guardians.map((guardian:{id:string;name:string;is_primary:boolean;relationship:string;phone:string|null;email:string|null})=><div className="attention-item" key={guardian.id}><div className="attention-icon blue"><ShieldCheck size={15}/></div><div><strong>{guardian.name}{guardian.is_primary?' · Primary':''}</strong><small>{guardian.relationship} · {guardian.phone || 'No phone'}<br/>{guardian.email || 'No email'}</small></div></div>)}</div></section>
  </>;
}
