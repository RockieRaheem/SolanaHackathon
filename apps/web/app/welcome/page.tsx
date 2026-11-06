'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Building2, HandHeart, HeartHandshake, LoaderCircle } from 'lucide-react';
import PortalShell from '@/components/PortalShell';
import { clientFetch as fetch } from '@/lib/api/client';

type Portal = {type:string;label:string;detail:string;href:string};

export default function WelcomePage() {
  const router=useRouter();
  const [portals,setPortals]=useState<Portal[]>([]),[name,setName]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{fetch('/api/backend/api/v1/me/portals').then(async response=>{const body=await response.json();if(!response.ok)throw new Error(body.detail||'Account options could not be loaded.');setPortals(body.portals);setName(body.display_name);}).catch(reason=>setError(reason.message)).finally(()=>setLoading(false));},[]);
  async function donor(event:FormEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError('');const form=new FormData(event.currentTarget);try{const response=await fetch('/api/backend/api/v1/me/donor-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:form.get('display_name'),show_public_name:form.get('show_public_name')==='on'})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Donor workspace could not be activated.');router.replace('/donor');}catch(reason){setError(reason instanceof Error?reason.message:'Donor workspace could not be activated.');setBusy(false);}}
  if(loading)return <PortalShell label="Account setup"><div className="portal-state"><LoaderCircle className="spin"/>Loading account options…</div></PortalShell>;
  return <PortalShell label="Account setup">
    <section className="portal-intro"><span>Welcome{name?`, ${name}`:''}</span><h1>Choose how you use HarambeeOne.</h1><p>Roles remain separate. A guardian needs a private school invitation; donors never gain access to learner identity.</p></section>
    {error&&<div className="portal-error" role="alert">{error}</div>}
    {portals.length>0&&<section className="portal-section"><h2>Your active workspaces</h2><div className="workspace-cards compact">{portals.map(item=><Link href={item.href} key={item.type}><span><strong>{item.label}</strong><small>{item.detail}</small></span></Link>)}</div></section>}
    <div className="account-choice-grid">
      <article><Building2/><h2>School staff</h2><p>Create a school workspace for authorized bursar operations and support review.</p><Link className="btn primary" href="/onboarding">Set up a school</Link></article>
      <article><HeartHandshake/><h2>Parent or guardian</h2><p>Use the private invitation supplied by the learner&apos;s school. It works only with the invited email address.</p><Link className="btn" href="/guardian/claim">Claim an invitation</Link></article>
      <article><HandHeart/><h2>Donor</h2><p>Activate a private dashboard for your contributions, receipts and verified updates.</p><form onSubmit={donor}><label>Display name<input name="display_name" minLength={2} maxLength={120} required defaultValue={name}/></label><label className="portal-check"><input type="checkbox" name="show_public_name"/>Allow this name on public acknowledgements</label><button className="btn primary" disabled={busy}>{busy?'Activating…':'Activate donor workspace'}</button></form></article>
    </div>
  </PortalShell>;
}
