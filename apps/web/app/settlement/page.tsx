import {
  CircleCheck,
  ExternalLink,
  HandHeart,
  Landmark,
  LockKeyhole,
  ShieldCheck,
  WalletCards,
} from 'lucide-react';

import { PageHeader, SectionHeader } from '@/components/ui';

const stages = [
  {
    number: '1',
    title: 'Invoice verified',
    detail: 'The school publishes a privacy-safe campaign linked to a real UGX obligation.',
  },
  {
    number: '2',
    title: 'Family contributes',
    detail: 'A parent, relative, sponsor or diaspora donor sends devnet SOL from their own wallet.',
  },
  {
    number: '3',
    title: 'Signature retained',
    detail: 'HarambeeOne records the public Solana signature beside the anonymous pledge reference.',
  },
  {
    number: '4',
    title: 'School verifies',
    detail: 'The bursar confirms the destination and amount before allocating value to the learner ledger.',
  },
];

export default function Settlement() {
  return (
    <>
      <PageHeader
        eyebrow="SomaFund · Solana devnet"
        title="Collaborative school-fee vault operations"
        description="A transparent contribution rail for verified school invoices, built on HarambeeOne's controlled UGX ledger."
        actions={
          <a
            className="btn primary"
            href="https://explorer.solana.com/?cluster=devnet"
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={16} />
            Open devnet explorer
          </a>
        }
      />

      <section className="panel" style={{ marginBottom: 18 }}>
        <SectionHeader
          title="Contribution and verification flow"
          subtitle="Every on-chain movement remains independently inspectable; learner identity stays off-chain"
        />
        <div className="flow-line">
          {stages.map((stage, index) => (
            <div style={{ display: 'contents' }} key={stage.number}>
              <div className={index < 2 ? 'flow-step done' : index === 2 ? 'flow-step active' : 'flow-step'}>
                <span>{stage.number}</span>
                <strong>{stage.title}</strong>
                <small>{stage.detail}</small>
              </div>
              {index < stages.length - 1 && <i className="flow-rule" />}
            </div>
          ))}
        </div>
      </section>

      <div className="content-grid">
        <section className="panel">
          <SectionHeader
            title="What Solana does in this MVP"
            subtitle="A real devnet payment path, not a simulated settlement table"
          />
          <div className="stack">
            <div className="policy-box">
              <h3><WalletCards size={18} /> Donor-controlled transfer</h3>
              <p>The donor connects a Wallet Standard wallet and authorises a direct devnet SOL transfer to the school-owned address.</p>
            </div>
            <div className="policy-box">
              <h3><CircleCheck size={18} /> Verifiable proof</h3>
              <p>The signature links the public contribution receipt to Solana Explorer while the private student record remains in Supabase.</p>
            </div>
            <div className="policy-box">
              <h3><HandHeart size={18} /> Shared contributions</h3>
              <p>Many contributors can fund the same verified invoice in small amounts, including relatives and diaspora sponsors.</p>
            </div>
          </div>
        </section>

        <aside className="stack">
          <section className="panel">
            <SectionHeader title="Hackathon safety gate" subtitle="Deliberately limited to devnet" />
            <div className="policy-box">
              <div className="policy-row"><span>Solana cluster</span><strong>Devnet</strong></div>
              <div className="policy-row"><span>Custody model</span><strong>Direct to school</strong></div>
              <div className="policy-row"><span>UGX conversion</span><strong>Demo quote only</strong></div>
              <div className="policy-row"><span>Mainnet funds</span><strong>Disabled</strong></div>
            </div>
          </section>
          <div className="notice">
            <strong><ShieldCheck size={16} /> Accounting rule</strong><br />
            A Solana signature proves a transfer. It does not by itself settle a school invoice; the bursar must verify and allocate the pledge.
          </div>
          <div className="notice">
            <strong><LockKeyhole size={16} /> Privacy rule</strong><br />
            No learner name, phone number, school identifier or invoice detail is written to Solana.
          </div>
          <div className="notice">
            <strong><Landmark size={16} /> Next production step</strong><br />
            Replace the direct-transfer MVP with an audited programme-derived vault before any mainnet or custody launch.
          </div>
        </aside>
      </div>
    </>
  );
}