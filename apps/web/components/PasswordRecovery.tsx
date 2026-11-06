'use client';

import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { CheckCircle2, LoaderCircle, LockKeyhole, Mail } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { authMessage } from '@/lib/auth-errors';

export default function PasswordRecovery({ mode }: { mode: 'request' | 'update' }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const supabase = createClient();
    try {
      if (mode === 'request') {
        const email = String(form.get('email') ?? '').trim().toLowerCase();
        const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent('/reset-password')}`;
        const { error: requestError } = await supabase.auth.resetPasswordForEmail(email, { redirectTo });
        if (requestError) throw requestError;
        setNotice(`If an account exists for ${email}, a secure reset link is on its way.`);
      } else {
        const password = String(form.get('password') ?? '');
        const confirmation = String(form.get('confirmation') ?? '');
        if (password.length < 10 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
          throw new Error('Use at least 10 characters with at least one letter and one number.');
        }
        if (password !== confirmation) throw new Error('The passwords do not match.');
        const { error: updateError } = await supabase.auth.updateUser({ password });
        if (updateError) throw updateError;
        setNotice('Your password has been updated securely.');
      }
    } catch (reason) {
      const localMessage = reason instanceof Error && !('code' in reason) ? reason.message : '';
      setError(localMessage || authMessage(reason, 'Password recovery could not be completed. Please try again.'));
    } finally {
      setBusy(false);
    }
  }

  const requesting = mode === 'request';
  return <main className="auth-page">
    <section className="auth-story" aria-label="About HarambeeOne">
      <Link className="auth-brand" href="/"><Image src="/harambeeone-logo.png" width={48} height={48} alt="" priority/><span><strong>HarambeeOne</strong><small>School finance, clearly managed</small></span></Link>
      <div className="auth-story-copy"><span className="auth-kicker">Protected account access</span><h1>Return to your workspace safely.</h1><p>Recovery links are time-limited and can only be used to update the account that requested them.</p></div>
      <footer>Secure access powered by Supabase</footer>
    </section>
    <section className="auth-panel"><div className="auth-card">
      <div className="auth-heading"><span>{requesting ? 'Account recovery' : 'Secure password update'}</span><h2>{requesting ? 'Reset your password' : 'Choose a new password'}</h2><p>{requesting ? 'Enter your work email and we will send a secure reset link.' : 'Use a password you have not used for this account before.'}</p></div>
      {error && <div className="auth-message error" role="alert">{error}</div>}
      {notice && <div className="auth-message success" role="status"><CheckCircle2 size={17}/>{notice}</div>}
      {!notice && <form className="auth-form" onSubmit={submit}>
        {requesting ? <label>Email address<div className="auth-input"><Mail size={17}/><input name="email" type="email" autoComplete="email" required placeholder="name@school.ac.ug"/></div></label> : <><label>New password<div className="auth-input"><LockKeyhole size={17}/><input name="password" type="password" autoComplete="new-password" minLength={10} required placeholder="10+ characters, including a number"/></div></label><label>Confirm new password<input name="confirmation" type="password" autoComplete="new-password" minLength={10} required placeholder="Repeat your password"/></label></>}
        <button className="auth-submit" disabled={busy}>{busy && <LoaderCircle className="spin" size={18}/>} {requesting ? 'Send secure reset link' : 'Update password'}</button>
      </form>}
      <p className="auth-switch">{requesting || !notice ? <Link href="/login">Return to sign in</Link> : <button type="button" className="auth-link-button" onClick={() => { router.replace('/workspace'); router.refresh(); }}>Continue to your workspace</button>}</p>
    </div></section>
  </main>;
}
