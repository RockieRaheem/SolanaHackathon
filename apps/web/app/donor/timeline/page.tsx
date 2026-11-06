'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import PortalShell from '@/components/PortalShell';
import { clientFetch as fetch } from '@/lib/api/client';

type Event={type:string;title:string;detail:string;occurred_at:string};
type Contribution={id:string;campaign_code:string;public_reference:string;amount:string;status:string;receipt_available:boolean;timeline:Event[]};
const money=(value:string)=>`UGX ${Number(value).toLocaleString('en-UG')}`;

export default function DonorTimelinePage(){
  const [items,setItems]=useState<Contribution[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
  useEffect(()=>{fetch('/api/backend/api/v1/support/donor/contributions').then(async response=>{const body=await response.json();if(!response.ok)throw new Error(body.detail||'Contribution timeline could not be loaded.');setItems(body);}).catch(reason=>setError(reason instanceof Error?reason.message:'Contribution timeline could not be loaded.')).finally(()=>setLoading(false));},[]);
  return <PortalShell label="Donor workspace"><section className="portal-intro"><span>Independent evidence</span><h1>From pledge to learner obligation.</h1><p>Each event comes from the school-controlled financial record. Updates contain no learner or guardian identity.</p></section>{error&&<div className="portal-error" role="alert">{error}</div>}{loading?<div className="portal-state">Loading contribution evidence…</div>:items.length?<section className="portal-section"><h2>Your campaign timelines</h2>{items.map(item=><article className="donor-timeline" key={item.id}><header><div><strong>{item.campaign_code}</strong><small>{item.public_reference}</small></div><b>{money(item.amount)}</b>{item.receipt_available&&<Link className="btn compact" href={`/donor/receipts/${item.id}`}>Official receipt</Link>}</header><ol>{item.timeline.map((event,index)=><li key={`${event.type}-${index}`}><span/><div><strong>{event.title}</strong><p>{event.detail}</p><small>{new Date(event.occurred_at).toLocaleString('en-UG')}</small></div></li>)}</ol></article>)}</section>:<div className="portal-empty"><History/><h2>No contribution evidence yet</h2><p>Your pledge, school verification, receipt and approved outcomes will appear here.</p><Link className="btn primary" href="/support">Browse campaigns</Link></div>}</PortalShell>;
}
