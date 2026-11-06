'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { LoaderCircle, ShieldCheck, Users } from 'lucide-react';
import PortalShell from '@/components/PortalShell';
import { clientFetch as fetch } from '@/lib/api/client';

function AcceptStaff(){const token=useSearchParams().get('token');const [state,setState]=useState<'loading'|'success'|'error'>('loading'),[message,setMessage]=useState('Verifying your secure invitation…'),[schoolId,setSchoolId]=useState('');useEffect(()=>{if(!token){setState('error');setMessage('This invitation link is incomplete.');return;}fetch('/api/backend/api/v1/staff-invitations/accept',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})}).then(async response=>{const body=await response.json();if(!response.ok)throw new Error(body.detail||'Invitation could not be accepted.');setSchoolId(body.school_id);setState('success');setMessage('Your section access is ready.');}).catch(reason=>{setState('error');setMessage(reason instanceof Error?reason.message:'Invitation could not be accepted.');});},[token]);return <PortalShell label="Staff invitation"><div className="portal-empty" role="status">{state==='loading'?<LoaderCircle className="spin"/>:state==='success'?<ShieldCheck/>:<Users/>}<h2>{state==='loading'?'Checking invitation':state==='success'?'Access confirmed':'Invitation unavailable'}</h2><p>{message}</p>{state==='success'&&<a className="btn primary" href={`/api/workspace/select?school_id=${schoolId}&next=/dashboard`}>Open bursar workspace</a>}{state==='error'&&<Link className="btn" href="/workspace">Return to workspaces</Link>}</div></PortalShell>}

export default function StaffAcceptPage(){return <Suspense fallback={<PortalShell label="Staff invitation"><div className="portal-empty"><LoaderCircle className="spin"/></div></PortalShell>}><AcceptStaff/></Suspense>}
