import Link from 'next/link';
import { ArrowLeft, CheckCircle2, ShieldCheck } from 'lucide-react';
import ReceiptActions from './ReceiptActions';
import { authorizedBackendFetch } from '@/lib/api/server';

const money=(value:string)=>`UGX ${Number(value).toLocaleString('en-UG',{minimumFractionDigits:2})}`;

export default async function ReceiptPage({params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  const response=await authorizedBackendFetch(`/api/v1/payments/${id}/receipt`).catch(()=>null);
  if(!response?.ok)return <div className="page-state"><h1>Receipt unavailable</h1><p>The finance service could not load this receipt.</p><Link className="btn" href="/payments">Back to payments</Link></div>;
  const receipt=await response.json(),issued=new Date(receipt.received_at);
  return <div className="receipt-page"><div className="receipt-toolbar no-print"><Link className="btn" href="/payments"><ArrowLeft size={16}/>Payment register</Link><ReceiptActions paymentId={id} reissueCount={receipt.reissue_count}/></div><article className="official-receipt">
    <header className="receipt-head"><div className="receipt-mark">H1</div><div><span>{receipt.transaction_type==='receipt'?'OFFICIAL SCHOOL RECEIPT':`OFFICIAL ${receipt.transaction_type.toUpperCase()}`}</span><h1>{receipt.school_name}</h1><p>{receipt.school_district||'Uganda'} · HarambeeOne finance ledger</p></div><div className="receipt-number"><small>Receipt number</small><strong>{receipt.receipt_no}</strong><span>{receipt.transaction_type==='receipt'?'PAID':'CORRECTION'}</span></div></header>
    <section className="receipt-meta"><div><small>Received from</small><strong>{receipt.payer_name||receipt.student_name}</strong></div><div><small>Date received</small><strong>{issued.toLocaleDateString('en-UG',{day:'2-digit',month:'long',year:'numeric'})}</strong></div><div><small>Payment method</small><strong>{receipt.channel.replaceAll('_',' ')}</strong></div><div><small>Source reference</small><strong>{receipt.external_reference}</strong></div></section>
    <section className="receipt-student"><small>Allocated to</small><h2>{receipt.student_name}</h2><p>Learner reference: <strong>{receipt.admission_no}</strong> · Purpose: <strong>{receipt.purpose}</strong></p></section>
    {receipt.original_payment_id&&<section className="receipt-correction"><strong>This is a linked {receipt.transaction_type}.</strong><p>{receipt.correction_reason}</p><Link href={`/payments/${receipt.original_payment_id}/receipt`}>View original receipt {receipt.original_receipt_no}</Link></section>}
    <section className="receipt-amount"><span>{receipt.transaction_type==='receipt'?'Amount received':`Amount ${receipt.transaction_type}ed`}</span><strong>{money(receipt.amount)}</strong><small>{receipt.note||receipt.purpose}</small></section>
    <section className="receipt-allocations"><h3>Allocation breakdown</h3>{receipt.allocations.map((item:{id:string;purpose:string;amount:string})=><div key={item.id}><span>{item.purpose}</span><strong>{money(item.amount)}</strong></div>)}</section>
    <section className="receipt-balances"><div><small>Total learner bill</small><strong>{money(receipt.billed)}</strong></div><div><small>Net paid to date</small><strong>{money(receipt.paid_to_date)}</strong></div><div><small>Balance remaining</small><strong>{money(receipt.balance)}</strong></div></section>
    <section className="receipt-proof"><ShieldCheck size={22}/><div><strong>Payment integrity reference</strong><p>{receipt.commitment_hash}</p></div><span className="confirmed">Recorded</span></section>
    <footer className="receipt-footer"><div><CheckCircle2 size={18}/><span>This receipt was generated from HarambeeOne&apos;s authoritative learner ledger.</span></div><p>Keep this receipt and quote its number when contacting the bursar.{receipt.reissue_count?` ${receipt.reissue_count} controlled reprint${receipt.reissue_count===1?'':'s'} recorded.`:''}</p></footer>
  </article></div>;
}
