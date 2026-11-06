'use client';

import Image from 'next/image';
import Link from 'next/link';
import { ArrowRight, CheckCircle2, LockKeyhole, ReceiptText, School, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { clientFetch as fetch } from '@/lib/api/client';

type Campaign = {
  public_code: string;
  title: string;
  public_summary: string;
  need_category: string;
  target_amount: string;
  verified_amount: string;
  pending_amount: string;
  currency: string;
  status: string;
  school: string;
};

const money = (value: string) => `UGX ${Number(value).toLocaleString('en-UG')}`;

export default function SupportCampaigns() {
  const [items, setItems] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/support/campaigns', { cache: 'no-store' })
      .then(async response => {
        const text = await response.text();
        let body:Campaign[] & { detail?:string };
        try { body = JSON.parse(text) as Campaign[] & { detail?:string }; }
        catch { throw new Error(`The campaign service returned an invalid response (${response.status}).`); }
        if (!response.ok) throw new Error(body.detail ?? 'Campaigns could not be loaded.');
        setItems(body);
      })
      .catch(reason => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  return <div className="support-site">
    <header className="support-header">
      <Link href="/support" className="support-brand">
        <Image src="/harambeeone-logo.png" alt="HarambeeOne" width={38} height={38}/>
        <span><strong>Harambee Support</strong><small>Verified school support</small></span>
      </Link>
      <div className="support-header-actions">
        <div className="support-trust"><ShieldCheck size={16}/> Privacy-first giving</div>
        <Link href="/support-admin" className="support-school-link"><School size={16}/> School workspace</Link>
      </div>
    </header>

    <main>
      <section className="support-hero">
        <div>
          <span className="support-kicker">Keep a learner learning</span>
          <h1>Support a verified school obligation, not an exposed child.</h1>
          <p>Each campaign begins with a real balance in a participating school. Identity stays private; every verified contribution is posted to the learner&apos;s school account and receives a traceable receipt.</p>
          <div className="support-hero-actions">
            <a href="#campaigns" className="support-primary-action">Explore campaigns <ArrowRight size={16}/></a>
            <Link href="/support-admin" className="support-secondary-action">Manage school campaigns</Link>
          </div>
        </div>
        <div className="support-proof-list">
          <div><LockKeyhole/><span><strong>Anonymous by design</strong><small>No learner names or photographs are published.</small></span></div>
          <div><ReceiptText/><span><strong>Allocated at the school</strong><small>Pledges count only after settlement is verified.</small></span></div>
          <div><CheckCircle2/><span><strong>Outcome evidence</strong><small>Schools publish redacted fulfilment and continuity updates.</small></span></div>
        </div>
      </section>

      <section className="support-campaign-section" id="campaigns">
        <div className="support-section-head">
          <div><span>Open campaigns</span><h2>Specific needs. Verifiable progress.</h2></div>
          <p>Pending pledges are shown separately and do not inflate funded totals.</p>
        </div>
        {loading && <div className="support-state">Loading verified campaigns…</div>}
        {error && <div className="support-state error">{error}</div>}
        {!loading && !error && !items.length && <div className="support-state support-empty-state">
          <strong>No public campaigns yet.</strong>
          <span>A campaign appears here after the school records consent, completes its review and an owner approves publication.</span>
          <Link href="/support-admin" className="support-primary-action">Create the first campaign <ArrowRight size={16}/></Link>
        </div>}
        <div className="support-cards">
          {items.map(item => {
            const percentage = Math.min(100, Number(item.verified_amount) / Number(item.target_amount) * 100);
            return <article className="support-card" key={item.public_code}>
              <div className="support-card-top"><span>{item.school}</span><em>{item.need_category.replaceAll('_', ' ')}</em></div>
              <h3>{item.title}</h3>
              <p>{item.public_summary}</p>
              <div className="support-progress">
                <div><i style={{ width: `${percentage}%` }}/></div>
                <span><strong>{money(item.verified_amount)}</strong> verified of {money(item.target_amount)}</span>
                {Number(item.pending_amount) > 0 && <small>{money(item.pending_amount)} awaiting verification</small>}
              </div>
              <Link href={`/support/${item.public_code}`}>View verified record <ArrowRight size={16}/></Link>
            </article>;
          })}
        </div>
      </section>
    </main>
    <footer className="support-footer"><span>HarambeeOne</span><p>Public transparency without public exposure.</p></footer>
  </div>;
}
