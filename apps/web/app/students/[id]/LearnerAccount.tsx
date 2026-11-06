'use client';

import { useEffect, useMemo, useState } from 'react';
import { Download, FileText, LoaderCircle, Printer, RefreshCw, Search } from 'lucide-react';
import { MetricCard, SectionHeader } from '@/components/ui';
import { getSelectedPeriod } from '@/lib/period';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type StatementLine = {
  id:string; occurred_at:string; entry_type:string; category:string; description:string;
  detail:string|null; reference:string|null; receipt_no:string|null; payer_name:string|null;
  components:{name:string;type:string;amount:string}[]; quantity:string|null; unit:string|null;
  status:string; amount:string; balance:string; is_financial:boolean;
};
type Statement = {
  school:{id:string;name:string}; student:{id:string;admission_no:string;name:string;status:string};
  guardian:{name:string;relationship:string;phone:string|null;email:string|null}|null;
  period:{id:string;name:string;academic_year:number;label:string;opening_date:string;closing_date:string};
  placement:{class_name:string|null;stream_name:string|null};
  summary:{opening_balance:string;charges:string;credits:string;payments:string;refunds:string;reversals:string;period_activity:string;closing_balance:string;physical_requirements:number};
  lines:StatementLine[]; generated_at:string;
};

const money=(value:string|number)=>`UGX ${Number(value).toLocaleString('en-UG',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const label=(value:string)=>value.replaceAll('_',' ').replace(/\b\w/g,letter=>letter.toUpperCase());

export default function LearnerAccount({studentId}:{studentId:string}){
  const [statement,setStatement]=useState<Statement|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [query,setQuery]=useState(''),[category,setCategory]=useState('all'),[downloading,setDownloading]=useState(false);

  async function load(){setLoading(true);setError('');try{const period=await getSelectedPeriod();const response=await fetch(`${API}/api/v1/students/${studentId}/statement?period_id=${period.id}`,{cache:'no-store'});const body=await response.json();if(!response.ok)throw new Error(body.detail??'Learner statement could not be loaded.');setStatement(body)}catch(reason){setError(reason instanceof Error?reason.message:'Learner statement could not be loaded.')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[studentId]);
  const categories=useMemo(()=>Array.from(new Set(statement?.lines.map(item=>item.category)??[])).sort(),[statement]);
  const visible=useMemo(()=>{const term=query.trim().toLowerCase();return (statement?.lines??[]).filter(item=>(category==='all'||item.category===category)&&(!term||`${item.description} ${item.detail??''} ${item.reference??''} ${item.payer_name??''}`.toLowerCase().includes(term)))},[category,query,statement]);

  async function download(){if(!statement)return;setDownloading(true);setError('');try{const response=await fetch(`${API}/api/v1/students/${studentId}/statement.csv?period_id=${statement.period.id}`);if(!response.ok){const body=await response.json();throw new Error(body.detail??'Statement download failed.')}const blob=await response.blob();const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=`${statement.student.admission_no}-${statement.period.academic_year}-${statement.period.name}.csv`;anchor.click();URL.revokeObjectURL(url)}catch(reason){setError(reason instanceof Error?reason.message:'Statement download failed.')}finally{setDownloading(false)}}

  if(loading)return <section className="panel account-state"><LoaderCircle className="spin"/><strong>Building learner account</strong><span>Recalculating the selected period from immutable ledger entries.</span></section>;
  if(error&&!statement)return <section className="panel account-state"><FileText/><strong>Statement unavailable</strong><span>{error}</span><button className="btn" onClick={load}><RefreshCw size={15}/>Try again</button></section>;
  if(!statement)return null;
  const placement=[statement.placement.class_name,statement.placement.stream_name].filter(Boolean).join(' · ')||'Unplaced';
  return <section className="learner-statement">
    {error&&<div className="form-error">{error}</div>}
    <div className="statement-heading">
      <div><span>Learner financial statement</span><h2>{statement.school.name}</h2><p>{statement.student.name} · {statement.student.admission_no} · {placement}</p></div>
      <div className="statement-period"><span>Statement period</span><strong>{statement.period.label}</strong><small>{new Date(`${statement.period.opening_date}T00:00:00`).toLocaleDateString('en-UG')} – {new Date(`${statement.period.closing_date}T00:00:00`).toLocaleDateString('en-UG')}</small></div>
    </div>
    <div className="statement-context"><div><span>Statement contact</span><strong>{statement.guardian?.name??'No statement contact'}</strong><small>{statement.guardian?[statement.guardian.relationship,statement.guardian.phone,statement.guardian.email].filter(Boolean).join(' · '):'Add an authorized guardian contact'}</small></div><div><span>Generated</span><strong>{new Date(statement.generated_at).toLocaleString('en-UG')}</strong><small>Account status: {statement.student.status}</small></div></div>
    <section className="metric-grid statement-metrics"><MetricCard icon={FileText} label="Opening balance" value={money(statement.summary.opening_balance)} note="Brought forward from earlier periods"/><MetricCard icon={FileText} label="Period charges" value={money(statement.summary.charges)} note={`${statement.summary.physical_requirements} physical requirement${statement.summary.physical_requirements===1?'':'s'}`} tone="blue"/><MetricCard icon={FileText} label="Payments & credits" value={money(Number(statement.summary.payments)+Number(statement.summary.credits))} note={`${money(statement.summary.payments)} paid · ${money(statement.summary.credits)} credited`} tone="green"/><MetricCard icon={FileText} label="Closing balance" value={money(statement.summary.closing_balance)} note="Recalculated after every entry" tone="amber"/></section>
    <section className="panel statement-register"><SectionHeader title="Account activity" subtitle="Positive entries increase the amount due; payments and credits reduce it." action={<div className="row-actions no-print"><button className="btn" onClick={()=>window.print()}><Printer size={15}/>Print</button><button className="btn" disabled={downloading} onClick={download}><Download size={15}/>{downloading?'Preparing…':'Download CSV'}</button></div>}/>
      <div className="table-tools no-print"><label className="table-search"><Search size={14}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search source, reference or payer"/></label><select value={category} onChange={event=>setCategory(event.target.value)}><option value="all">All account categories</option>{categories.map(item=><option key={item} value={item}>{label(item)}</option>)}</select><span className="filter-summary"><strong>{visible.length}</strong> of {statement.lines.length} entries</span></div>
      <div className="table-wrap"><table className="data-table statement-table"><thead><tr><th>Date</th><th>Account source</th><th>Reference</th><th>Charge</th><th>Payment / credit</th><th>Balance</th></tr></thead><tbody>{visible.map(item=>{const amount=Number(item.amount);return <tr key={item.id}><td>{new Date(item.occurred_at).toLocaleDateString('en-UG')}</td><td className="entity"><strong>{item.description}</strong><small>{label(item.category)} · {item.status}{item.quantity?` · ${Number(item.quantity)} ${item.unit}`:''}</small>{item.components.length>0&&<span className="statement-components">{item.components.map(component=>`${component.name} ${money(component.amount)}`).join(' · ')}</span>}{item.payer_name&&<span className="statement-components">Paid by {item.payer_name}</span>}</td><td className="entity"><strong>{item.receipt_no??item.reference??'—'}</strong><small>{item.detail??item.entry_type.replaceAll('_',' ')}</small></td><td className="amount">{item.is_financial&&amount>0?money(amount):'—'}</td><td className="amount credit-amount">{item.is_financial&&amount<0?money(Math.abs(amount)):'—'}</td><td className="amount"><strong>{money(item.balance)}</strong></td></tr>})}{!visible.length&&<tr><td colSpan={6}><div className="empty-register"><FileText/><strong>{statement.lines.length?'No entries match these filters':'No account activity in this period'}</strong><span>{statement.lines.length?'Clear the search or select another category.':'The statement is valid and its closing balance equals the opening balance.'}</span></div></td></tr>}</tbody></table></div>
      <footer className="statement-total"><span>Closing balance</span><strong>{money(statement.summary.closing_balance)}</strong></footer>
    </section>
  </section>
}
