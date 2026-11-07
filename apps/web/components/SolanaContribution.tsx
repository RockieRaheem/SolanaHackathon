'use client';

import { address, type Instruction, lamports } from '@solana/kit';
import { getTransferSolInstruction } from '@solana-program/system';
import {
  useConnect,
  useConnectedWallet,
  useDisconnect,
  useWallets,
  useWalletStatus,
} from '@solana/kit-plugin-wallet/react';
import { useClient } from '@solana/react';
import { CheckCircle2, ExternalLink, LockKeyhole, WalletCards } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import type { SolanaClient } from '@/lib/solana/client';

type Destination = {
  id: string;
  channel: string;
  account_name: string;
  account_reference: string;
};

type Campaign = {
  public_code: string;
  remaining_amount: string;
  payment_destinations: Destination[];
};

type SolanaIntent = {
  public_reference: string;
  amount: string;
  recipient_address: string;
  expected_lamports: number;
  quote_ugx_per_sol: string;
  memo: string;
  cluster: string;
  expires_at: string;
};

type Confirmation = {
  public_reference: string;
  status: string;
  receipt_no: string;
  transaction_signature: string;
  confirmation_slot: number;
  campaign_status: string;
};

const memoProgram = address('MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr');

export default function SolanaContribution({ code }: { code: string }) {
  const client = useClient<SolanaClient>();
  const walletStatus = useWalletStatus(client);
  const wallets = useWallets(client);
  const connected = useConnectedWallet(client);
  const connect = useConnect(client);
  const disconnect = useDisconnect(client);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [amount, setAmount] = useState('');
  const [donorName, setDonorName] = useState('');
  const [error, setError] = useState('');
  const [phase, setPhase] = useState('');
  const [signature, setSignature] = useState('');
  const [intent, setIntent] = useState<SolanaIntent | null>(null);
  const [confirmed, setConfirmed] = useState<Confirmation | null>(null);
  const checkoutKey = useRef('');

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/support/campaigns/${encodeURIComponent(code)}`, { cache: 'no-store' })
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || 'Campaign could not be loaded.');
        if (!cancelled) setCampaign(body);
      })
      .catch(reason => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Campaign could not be loaded.');
      });
    return () => { cancelled = true; };
  }, [code]);

  const destination = useMemo(
    () => campaign?.payment_destinations.find(item => item.channel === 'solana'),
    [campaign],
  );

  async function request(path: string, body: object) {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'The donation request could not be completed.');
    return result;
  }

  async function confirmTransfer(activeIntent: SolanaIntent, transactionSignature: string) {
    if (!connected) throw new Error('Reconnect the wallet that made this transfer.');
    setPhase('Verifying the confirmed transaction and posting the school receipt...');
    const result = await request(
      `/api/support/campaigns/${encodeURIComponent(code)}/solana-intents/${encodeURIComponent(activeIntent.public_reference)}/confirm`,
      { transaction_signature: transactionSignature.trim(), sender_address: connected.account.address },
    ) as Confirmation;
    setConfirmed(result);
    setPhase('');
  }

  async function contribute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!campaign || !destination || !connected?.signer) return;
    const ugxAmount = Number(amount);
    if (!Number.isSafeInteger(ugxAmount) || ugxAmount <= 0 || ugxAmount > Number(campaign.remaining_amount)) {
      setError('Enter a whole UGX amount within the remaining verified school obligation.');
      return;
    }
    setError('');
    setConfirmed(null);
    if (!checkoutKey.current) checkoutKey.current = crypto.randomUUID();
    try {
      setPhase('Creating a protected checkout...');
      const profile = await fetch('/api/backend/api/v1/donor/profile', { cache: 'no-store' });
      const createPath = profile.ok
        ? `/api/backend/api/v1/support/donor/campaigns/${encodeURIComponent(code)}/solana-intents`
        : `/api/support/campaigns/${encodeURIComponent(code)}/solana-intents`;
      const created = await request(createPath, {
        amount: ugxAmount,
        payment_destination_id: destination.id,
        donor_display_name: donorName.trim() || null,
        idempotency_key: checkoutKey.current,
      }) as SolanaIntent;
      setIntent(created);
      setPhase('Approve the exact transfer in your wallet...');
      const transfer = getTransferSolInstruction({
        source: connected.signer,
        destination: address(created.recipient_address),
        amount: lamports(BigInt(created.expected_lamports)),
      });
      const memo: Instruction = {
        programAddress: memoProgram,
        data: new TextEncoder().encode(created.memo),
      };
      const result = await client.sendTransaction([transfer, memo]);
      const transactionSignature = String(result.context.signature);
      setSignature(transactionSignature);
      await confirmTransfer(created, transactionSignature);
    } catch (reason) {
      setPhase('');
      setError(reason instanceof Error ? reason.message : 'The Solana contribution could not be completed.');
    }
  }

  async function retryConfirmation() {
    if (!intent || !signature.trim()) return;
    setError('');
    try {
      await confirmTransfer(intent, signature);
    } catch (reason) {
      setPhase('');
      setError(reason instanceof Error ? reason.message : 'Confirmation could not be retried.');
    }
  }

  if (!destination) return null;
  const explorer = signature
    ? `https://explorer.solana.com/tx/${encodeURIComponent(signature)}?cluster=devnet`
    : '';
  const quote = intent ? Number(intent.quote_ugx_per_sol) : 750000;
  const approximateSol = amount && quote > 0 ? Number(amount) / quote : 0;

  return <section className="solana-vault" aria-labelledby="solana-vault-title">
    <header>
      <div><WalletCards/><span><small>Verified rail · Solana devnet</small><h2 id="solana-vault-title">SomaFund school-fee vault</h2></span></div>
      <b>On-chain proof</b>
    </header>
    <p>Contribute directly to the school&apos;s verified wallet. HarambeeOne checks the signer, exact amount, destination and campaign memo on Solana before automatically crediting the learner&apos;s private school account.</p>
    <div className="solana-destination">
      <LockKeyhole/>
      <span><small>Verified institution wallet</small><strong>{destination.account_name}</strong><code>{destination.account_reference}</code></span>
    </div>

    {walletStatus === 'pending' ? <p className="solana-status">Discovering wallets...</p> : !connected ? <div className="solana-wallets">
      {wallets.length ? wallets.map(wallet => <button type="button" key={wallet.name} disabled={connect.isRunning} onClick={() => connect.dispatch(wallet)}>Connect {wallet.name}</button>) : <p className="solana-status">Install a Wallet Standard wallet such as Phantom or Solflare, then refresh.</p>}
    </div> : <form onSubmit={contribute}>
      <div className="solana-account"><span>Connected</span><code>{connected.account.address}</code><button type="button" onClick={() => disconnect.dispatch()}>Disconnect</button></div>
      <label>Contribution amount (UGX)<input type="number" min="1" step="1" max={Number(campaign?.remaining_amount || 0)} value={amount} onChange={event => setAmount(event.target.value)} required/><small>Judging quote: UGX {quote.toLocaleString('en-UG')} = 1 devnet SOL · approximately {approximateSol.toFixed(6)} SOL</small></label>
      <label>Name shown to school <span>optional</span><input value={donorName} onChange={event => setDonorName(event.target.value)} placeholder="Anonymous donor"/></label>
      <button className="solana-submit" disabled={Boolean(phase) || !connected.signer || Boolean(confirmed)}>{phase || (confirmed ? 'Contribution confirmed' : 'Contribute securely on Solana')}</button>
    </form>}

    {error && <div className="solana-error" role="alert">{error}</div>}
    {intent && signature && !confirmed && <div className="solana-recovery">
      <strong>Transfer sent but receipt not posted?</strong>
      <p>Keep this signature and retry. HarambeeOne will never post it twice.</p>
      <input aria-label="Solana transaction signature" value={signature} onChange={event => setSignature(event.target.value)} />
      <button type="button" disabled={Boolean(phase)} onClick={retryConfirmation}>Retry confirmation</button>
    </div>}
    {signature && <a className="solana-proof" href={explorer} target="_blank" rel="noreferrer">View verified devnet transaction <ExternalLink/></a>}
    {confirmed && <div className="solana-success"><CheckCircle2/><strong>Contribution confirmed and credited</strong><span>Official school receipt {confirmed.receipt_no}</span><code>{confirmed.public_reference}</code><small>Confirmed in slot {confirmed.confirmation_slot.toLocaleString('en-UG')}</small></div>}
    <footer>Devnet demonstration: no real money is used. Learner identity and school balances remain off-chain; only the public transfer and anonymous campaign memo are on Solana.</footer>
  </section>;
}
