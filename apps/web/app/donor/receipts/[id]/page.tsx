import Link from 'next/link';
import { notFound, redirect } from 'next/navigation';
import PortalShell from '@/components/PortalShell';
import { authorizedBackendFetch } from '@/lib/api/server';
import ReceiptActions from './ReceiptActions';

type Receipt={receipt_no:string;issued_at:string;school_name:string;school_district:string|null;campaign_code:string;campaign_title:string;need_category:string;amount:string;currency:string;donor_name:string;channel:string;provider_name:string|null;settlement_reference:string|null;status:string;allocation_statement:string;privacy_statement:string};
const money=(value:string)=>`UGX ${Number(value).toLocaleString('en-UG')}`;

export default async function DonorReceiptPage({params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  const response=await authorizedBackendFetch(`/api/v1/support/donor/contributions/${id}/receipt`);
  if(response.status===401)redirect(`/login?error=session_expired&next=/donor/receipts/${id}`);
  if(response.status===404)notFound();
  if(!response.ok)throw new Error('The official receipt could not be loaded.');
  const receipt:Receipt=await response.json();
  return <PortalShell label="Donor receipt"><div className="donor-receipt-page"><Link href="/donor">← Contribution history</Link><section id="official-donor-receipt"><header><small>Official school receipt</small><h1>{receipt.receipt_no}</h1><p>{receipt.school_name}{receipt.school_district?` · ${receipt.school_district}`:''}</p></header><dl><div><dt>Campaign</dt><dd>{receipt.campaign_code} · {receipt.campaign_title}</dd></div><div><dt>Amount received</dt><dd>{money(receipt.amount)}</dd></div><div><dt>Settlement</dt><dd>{receipt.provider_name??receipt.channel} · {receipt.settlement_reference}</dd></div><div><dt>Verified</dt><dd>{new Date(receipt.issued_at).toLocaleString('en-UG')}</dd></div><div><dt>Status</dt><dd>{receipt.status}</dd></div></dl><p>{receipt.allocation_statement}</p><small>{receipt.privacy_statement}</small></section><ReceiptActions receiptNo={receipt.receipt_no}/></div></PortalShell>;
}
