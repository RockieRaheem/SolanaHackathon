'use client';

import Image from 'next/image';
import Link from 'next/link';
import { CheckCircle2, LoaderCircle, LockKeyhole, Mail } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { authMessage } from '@/lib/auth-errors';
import { passwordProblem } from '@/lib/auth-policy';

export default function PasswordRecovery({ mode }: { mode: 'request' | 'update' }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    try {
      const email = String(form.get('email') ?? '').trim().toLowerCase();
      const password = String(form.get('password') ?? '');
      if (mode === 'update') {
        const confirmation = String(form.get('confirmation') ?? '');
        const problem = passwordProblem(password);
        if (problem) throw new Error(problem);
        if (password !== confirmation) throw new Error('The passwords do not match.');
      }
      const response = await fetch('/auth/recovery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({ action: mode, email, password }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw Object.assign(new Error(authMessage(result, result.detail)), { code: result.code });
      }
      setNotice(mode === 'request'
        ? 'If an account exists for that address, a secure reset link is on its way.'
        : 'Your password has been updated. Sign in again with the new password.');
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
        {requesting ? <label>Email address<div className="auth-input"><Mail size={17}/><input name="email" type="email" autoComplete="email" required placeholder="name@school.ac.ug"/></div></label> : <><label>New password<div className="auth-input"><LockKeyhole size={17}/><input name="password" type="password" autoComplete="new-password" minLength={12} required placeholder="12+ characters with upper/lowercase, number and symbol"/></div></label><label>Confirm new password<input name="confirmation" type="password" autoComplete="new-password" minLength={12} required placeholder="Repeat your password"/></label></>}
        <button className="auth-submit" disabled={busy}>{busy && <LoaderCircle className="spin" size={18}/>} {requesting ? 'Send secure reset link' : 'Update password'}</button>
      </form>}
      <p className="auth-switch"><Link href="/login">{!requesting && notice ? 'Sign in with your new password' : 'Return to sign in'}</Link></p>
    </div></section>
  </main>;
}