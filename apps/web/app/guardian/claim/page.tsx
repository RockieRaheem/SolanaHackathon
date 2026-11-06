'use client';

import { FormEvent, Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { KeyRound } from 'lucide-react';
import PortalShell from '@/components/PortalShell';
import { clientFetch as fetch } from '@/lib/api/client';

function ClaimForm(){
  const router=useRouter();
  const params=useSearchParams();
  const [token,setToken]=useState(params.get('token')??''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function submit(event:FormEvent){event.preventDefault();setBusy(true);setError('');try{const response=await fetch('/api/backend/api/v1/guardian/invitations/accept',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token.trim()})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Invitation could not be accepted.');router.replace('/guardian');}catch(reason){setError(reason instanceof Error?reason.message:'Invitation could not be accepted.');setBusy(false);}}
  return <PortalShell label="Guardian access"><section className="claim-card"><KeyRound/><span>Private school invitation</span><h1>Connect your guardian account</h1><p>Sign in with the exact email address invited by the school. The invitation expires after 72 hours and can be used only once.</p>{error&&<div className="portal-error" role="alert">{error}</div>}<form onSubmit={submit}><label>Invitation code or token<input value={token} onChange={event=>setToken(event.target.value)} minLength={32} required autoComplete="off"/></label><button className="btn primary" disabled={busy||token.trim().length<32}>{busy?'Verifying…':'Connect learner account'}</button></form></section></PortalShell>;
}

export default function GuardianClaimPage(){return <Suspense fallback={<PortalShell label="Guardian access"><div className="portal-state">Loading invitation…</div></PortalShell>}><ClaimForm/></Suspense>;}
