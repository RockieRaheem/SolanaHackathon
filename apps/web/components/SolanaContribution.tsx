'use client';

import { address, lamports } from '@solana/kit';
import { getTransferSolInstruction } from '@solana-program/system';
import {
  useConnect,
  useConnectedWallet,
  useDisconnect,
  useWallets,
  useWalletStatus,
} from '@solana/kit-plugin-wallet/react';
import { useClient } from '@solana/react';
import { ExternalLink, LockKeyhole, WalletCards } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import type { SolanaClient } from '@/lib/solana/client';

type Destination = {
  id: string;
  channel: string;
  label: string;
  provider_name: string;
  account_name: string;
  account_reference: string;
  instructions: string;
};

type Campaign = {
  public_code: string;
  remaining_amount: string;
  payment_destinations: Destination[];
};

type RecordedPledge = {
  public_reference: string;
  message: string;
};

const quote = Number(process.env.NEXT_PUBLIC_SOLANA_DEMO_UGX_PER_SOL || '750000');

export default function SolanaContribution({ code }: { code: string }) {
  const client = useClient<SolanaClient>();
  const status = useWalletStatus(client);
  const wallets = useWallets(client);
  const connected = useConnectedWallet(client);
  const connect = useConnect(client);
  const disconnect = useDisconnect(client);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [amount, setAmount] = useState('');
  const [donorName, setDonorName] = useState('');
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [signature, setSignature] = useState('');
  const [recorded, setRecorded] = useState<RecordedPledge | null>(null);
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

  const destinations = useMemo(
    () => campaign?.payment_destinations.filter(item => item.channel === 'solana') || [],
    [campaign],
  );
  const destination = destinations[0];
  const solAmount = amount && quote > 0 ? Number(amount) / quote : 0;

  async function contribute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!campaign || !destination || !connected?.signer) return;
    const ugxAmount = Number(amount);
    if (!Number.isFinite(ugxAmount) || ugxAmount <= 0 || ugxAmount > Number(campaign.remaining_amount)) {
      setError('Enter an amount within the remaining verified school obligation.');
      return;
    }
    const transferLamports = BigInt(Math.round((ugxAmount / quote) * 1_000_000_000));
    if (transferLamports < 1n) {
      setError('The amount is too small for this demonstration quote.');
      return;
    }

    setSending(true);
    setError('');
    setRecorded(null);
    try {
      const transfer = getTransferSolInstruction({
        source: connected.signer,
        destination: address(destination.account_reference),
        amount: lamports(transferLamports),
      });
      const result = await client.sendTransaction([transfer]);
      const transactionSignature = String(result.context.signature);
      setSignature(transactionSignature);
      if (!checkoutKey.current) checkoutKey.current = crypto.randomUUID();

      const profile = await fetch('/api/backend/api/v1/donor/profile', { cache: 'no-store' });
      const path = profile.ok
        ? `/api/backend/api/v1/support/donor/campaigns/${code}/pledges`
        : `/api/support/campaigns/${code}/pledges`;
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: ugxAmount,
          payment_destination_id: destination.id,
          external_reference: transactionSignature,
          donor_display_name: donorName.trim() || null,
          idempotency_key: checkoutKey.current,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          `The transfer succeeded but HarambeeOne could not record it. Keep signature ${transactionSignature}. ${body.detail || ''}`,
        );
      }
      setRecorded(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The Solana contribution could not be completed.');
    } finally {
      setSending(false);
    }
  }

  if (!destination) return null;

  const explorer = signature
    ? `https://explorer.solana.com/tx/${encodeURIComponent(signature)}?cluster=devnet`
    : '';

  return <section className="solana-vault" aria-labelledby="solana-vault-title">
    <header>
      <div><WalletCards/><span><small>DeFi rail - Solana devnet</small><h2 id="solana-vault-title">SomaFund school-fee vault</h2></span></div>
      <b>~1 second settlement</b>
    </header>
    <p>Send devnet SOL from your wallet to the school&apos;s verified wallet. HarambeeOne links the public signature to this anonymous obligation; learner identity never goes on-chain.</p>
    <div className="solana-destination">
      <LockKeyhole/>
      <span><small>Verified institution wallet</small><strong>{destination.account_name}</strong><code>{destination.account_reference}</code></span>
    </div>

    {status === 'pending' ? <p className="solana-status">Discovering wallets...</p> : !connected ? <div className="solana-wallets">
      {wallets.length ? wallets.map(wallet => <button type="button" key={wallet.name} disabled={connect.isRunning} onClick={() => connect.dispatch(wallet)}>Connect {wallet.name}</button>) : <p className="solana-status">Install a Wallet Standard wallet such as Phantom or Solflare, then refresh.</p>}
    </div> : <form onSubmit={contribute}>
      <div className="solana-account"><span>Connected</span><code>{connected.account.address}</code><button type="button" onClick={() => disconnect.dispatch()}>Disconnect</button></div>
      <label>Contribution amount (UGX)<input type="number" min="1" max={Number(campaign?.remaining_amount || 0)} value={amount} onChange={event => setAmount(event.target.value)} required/><small>Hackathon quote: UGX {quote.toLocaleString('en-UG')} = 1 SOL - sends approximately {solAmount.toFixed(6)} SOL</small></label>
      <label>Name shown to school <span>optional</span><input value={donorName} onChange={event => setDonorName(event.target.value)} placeholder="Anonymous donor"/></label>
      <button className="solana-submit" disabled={sending || !connected.signer}>{sending ? 'Confirming on Solana...' : 'Contribute on Solana'}</button>
    </form>}

    {error && <div className="solana-error" role="alert">{error}</div>}
    {signature && <a className="solana-proof" href={explorer} target="_blank" rel="noreferrer">View devnet transaction <ExternalLink/></a>}
    {recorded && <div className="solana-success"><strong>Contribution recorded for school verification</strong><span>{recorded.message}</span><code>{recorded.public_reference}</code></div>}
    <footer>Devnet direct-to-school demonstration only. The displayed UGX/SOL quote is fixed for judging and is not a production exchange rate.</footer>
  </section>;
}
