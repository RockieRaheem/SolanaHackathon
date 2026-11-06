'use client';

import { Check, FileCheck2, ShieldCheck, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import NotificationCenter from '@/components/NotificationCenter';
import { PageHeader } from '@/components/ui';
import { clientFetch as fetch } from '@/lib/api/client';
import { getPrimarySchool } from '@/lib/school';

type Evidence={id:string;campaign_code:string;campaign_title:string;type:string;statement:string;redacted_statement:string|null;attendance_band:string|null;evidence_hash:string|null;status:string;submitted_by_role:string;submitted_at:string;rejection_reason:string|null};

export default function OutcomeEvidencePage(){
  const [schoolId,setSchoolId]=useState(''),[schoolRole,setSchoolRole]=useState(''),[items,setItems]=useState<Evidence[]>([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const load=useCallback(async(id:string)=>{setLoading(true);try{const response=await fetch(`/api/backend/api/v1/support/attestations?school_id=${id}`);const body=await response.json();if(!response.ok)throw new Error(body.detail||'Outcome evidence could not be loaded.');setItems(body);}catch(reason){setError(reason instanceof Error?reason.message:'Outcome evidence could not be loaded.');}finally{setLoading(false);}},[]);
  useEffect(()=>{getPrimarySchool().then(school=>{setSchoolId(school.id);setSchoolRole(school.role??'');return load(school.id);}).catch(reason=>setError(reason.message));},[load]);
  async function review(item:Evidence,action:'approve'|'reject'){
    const redacted=action==='approve'?window.prompt('Edit the privacy-safe statement donors may see:',item.statement):null;
    if(action==='approve'&&!redacted)return;
    const reason=action==='reject'?window.prompt('Why is this evidence being returned?'):null;
    if(action==='reject'&&!reason)return;
    setBusy(item.id);setError('');setNotice('');
    try{const response=await fetch(`/api/backend/api/v1/support/attestations/${item.id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,redacted_statement:redacted,reason})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Review could not be saved.');setNotice(action==='approve'?'The redacted outcome is now visible to donors.':'The evidence was returned for revision.');await load(schoolId);}catch(reasonValue){setError(reasonValue instanceof Error?reasonValue.message:'Review could not be saved.');}finally{setBusy('');}
  }
  return <><NotificationCenter compact/><PageHeader eyebrow="Learner support · Outcome assurance" title="Review outcome evidence" description="Private school and guardian statements stay hidden until an owner approves a redacted, non-identifying version."/>{error&&<div className="error-banner" role="alert">{error}</div>}{notice&&<div className="success-banner" role="status">{notice}</div>}<section className="card"><header className="section-heading"><div><span>Human review queue</span><h2>Evidence and continuity updates</h2></div><ShieldCheck size={20}/></header>{loading?<div className="empty-state">Loading outcome evidence…</div>:items.length?<div>{items.map(item=><article className="support-outcome-row" key={item.id}><div><span>{item.campaign_code} · {item.submitted_by_role}</span><h3>{item.campaign_title}</h3><p>{item.statement}</p>{item.redacted_statement&&<small>Published: {item.redacted_statement}</small>}</div><strong className={`status ${item.status}`}>{item.status}</strong>{item.status==='submitted'&&schoolRole==='owner'&&<div><button className="btn primary" disabled={busy===item.id} onClick={()=>void review(item,'approve')}><Check size={14}/>Approve redacted update</button><button className="btn" disabled={busy===item.id} onClick={()=>void review(item,'reject')}><X size={14}/>Return</button></div>}</article>)}</div>:<div className="empty-state"><FileCheck2/><h3>No outcome evidence yet</h3><p>Funded campaigns can receive school fulfilment, enrolment, or guardian acknowledgement updates.</p></div>}</section></>;
}
