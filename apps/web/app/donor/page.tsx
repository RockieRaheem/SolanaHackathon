import Link from 'next/link';
import { redirect } from 'next/navigation';
import { HandHeart, ReceiptText, ShieldCheck } from 'lucide-react';
import PortalShell from '@/components/PortalShell';
import { authorizedBackendFetch } from '@/lib/api/server';

type Profile={display_name:string;show_public_name:boolean};
type Contribution={id:string;public_reference:string;campaign_code:string;amount:string;currency:string;status:string;created_at:string;verified_at:string|null;receipt_available:boolean};
const money=(value:string)=>`UGX ${Number(value).toLocaleString('en-UG')}`;

export default async function DonorPage(){
  const [profileResponse,contributionResponse]=await Promise.all([
    authorizedBackendFetch('/api/v1/donor/profile'),
    authorizedBackendFetch('/api/v1/support/donor/contributions'),
  ]);
  if(profileResponse.status===401)redirect('/login?error=session_expired&next=/donor');
  if(profileResponse.status===403||profileResponse.status===404)redirect('/welcome');
  if(!profileResponse.ok)return <PortalShell label="Donor workspace"><div className="portal-empty" role="alert"><HandHeart/><h2>We could not load your donor workspace</h2><p>Your account is safe. The service may be temporarily unavailable.</p><Link className="btn primary" href="/donor">Try again</Link></div></PortalShell>;
  const profile:Profile=await profileResponse.json();
  const contributions:Contribution[]=contributionResponse.ok?await contributionResponse.json():[];
  const verified=contributions.filter(item=>item.status==='verified').reduce((sum,item)=>sum+Number(item.amount),0);
  return <PortalShell label="Donor workspace"><section className="portal-intro"><span>Welcome, {profile.display_name}</span><h1>Your support, independently recorded.</h1><p>Track school confirmation, retrieve official receipts and follow each anonymous campaign without exposing a learner.</p></section><section className="donor-summary"><article><HandHeart/><span>Contributions</span><strong>{contributions.length}</strong><small>{money(String(verified))} currently verified.</small></article><article><ReceiptText/><span>Receipts</span><strong>{contributions.filter(item=>item.receipt_available).length}</strong><small>Issued only after school settlement verification.</small></article><article><ShieldCheck/><span>Public name</span><strong>{profile.show_public_name?'Enabled':'Private'}</strong><small>Learner identity always stays private.</small></article></section>{contributions.length?<section className="portal-list"><header><h2>Contribution history</h2><Link className="btn" href="/support">Support another campaign</Link></header>{contributions.map(item=><article key={item.id}><div><strong>{item.campaign_code}</strong><small>{item.public_reference} · {new Date(item.created_at).toLocaleDateString('en-UG')}</small></div><b>{money(item.amount)}</b><span className={`status ${item.status}`}>{item.status}</span>{item.receipt_available?<Link className="btn compact" href={`/donor/receipts/${item.id}`}>View receipt</Link>:<small>Awaiting school verification</small>}</article>)}</section>:<div className="portal-empty"><HandHeart/><h2>Choose a verified campaign</h2><p>Pending contributions do not increase campaign totals until the school confirms the funds.</p><Link className="btn primary" href="/support">Browse campaigns</Link></div>}</PortalShell>;
}
