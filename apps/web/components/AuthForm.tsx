'use client';

import Image from 'next/image';
import Link from 'next/link';
import { Eye, EyeOff, LoaderCircle, LockKeyhole, Mail } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { authMessage } from '@/lib/auth-errors';
import { markSessionRecovered } from '@/lib/api/client';
import { clearPrimarySchool } from '@/lib/school';
import { clearPeriods } from '@/lib/period';

type AuthFormProps = {
  mode: 'login' | 'signup';
  nextPath?: string;
  initialError?: string;
};

function GoogleLogo() {
  return <svg className="google-logo" viewBox="0 0 18 18" aria-hidden="true">
    <path fill="#4285F4" d="M17.64 9.205c0-.638-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 0 1-1.797 2.716v2.259h2.909c1.703-1.568 2.684-3.878 2.684-6.615Z" />
    <path fill="#34A853" d="M9 18c2.43 0 4.468-.806 5.956-2.18l-2.909-2.259c-.806.54-1.835.859-3.047.859-2.344 0-4.328-1.585-5.037-3.714H.956v2.332A9 9 0 0 0 9 18Z" />
    <path fill="#FBBC05" d="M3.963 10.706A5.41 5.41 0 0 1 3.682 9c0-.592.102-1.168.281-1.706V4.962H.956A9 9 0 0 0 0 9c0 1.452.347 2.827.956 4.038l3.007-2.332Z" />
    <path fill="#EA4335" d="M9 3.58c1.321 0 2.507.454 3.441 1.346l2.581-2.581C13.464.892 11.427 0 9 0A9 9 0 0 0 .956 4.962l3.007 2.332C4.672 5.165 6.656 3.58 9 3.58Z" />
  </svg>;
}

function passwordProblem(password: string) {
  if (password.length < 10) return 'Use at least 10 characters for your password.';
  if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) return 'Include at least one letter and one number.';
  return '';
}

export default function AuthForm({ mode, nextPath = '/dashboard', initialError = '' }: AuthFormProps) {
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(initialError);
  const [notice, setNotice] = useState('');
  const isLogin = mode === 'login';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');

    const form = new FormData(event.currentTarget);
    const email = String(form.get('email') ?? '').trim().toLowerCase();
    const password = String(form.get('password') ?? '');

    try {
      const fullName = String(form.get('fullName') ?? '').trim();
      if (!isLogin) {
        const confirmation = String(form.get('confirmation') ?? '');
        if (password !== confirmation) throw new Error('The passwords do not match.');
        const problem = passwordProblem(password);
        if (problem) throw new Error(problem);
      }
      const response = await fetch('/auth/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({ mode, email, password, fullName, nextPath }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const authFailure = { code: result.code, status: response.status };
        const message = authMessage(authFailure, result.detail || 'Authentication could not be completed.');
        throw Object.assign(new Error(message), { code: result.code });
      }
      if (result.authenticated) {
        markSessionRecovered();
        clearPrimarySchool();
        clearPeriods();
        window.location.replace(nextPath);
      } else {
        setNotice(`We sent a confirmation link to ${email}. Open it on this device to finish creating your account.`);
      }
    } catch (reason) {
      const localMessage = reason instanceof Error ? reason.message : '';
      setError(localMessage || authMessage(reason, isLogin ? 'Sign-in could not be completed. Check your details and try again.' : 'Your account could not be created. Please try again.'));
    } finally {
      setBusy(false);
    }
  }

  function continueWithGoogle() {
    setGoogleBusy(true);
    setError('');
    window.location.assign(`/auth/google?next=${encodeURIComponent(nextPath)}`);
  }

  return <main className="auth-page">
    <section className="auth-story" aria-label="About HarambeeOne">
      <Link className="auth-brand" href="/">
        <Image src="/harambeeone-logo.png" width={48} height={48} alt="" priority />
        <span><strong>HarambeeOne</strong><small>School finance, clearly managed</small></span>
      </Link>
      <div className="auth-story-copy">
        <span className="auth-kicker">Built for the bursar&apos;s office</span>
        <h1>Every learner account, payment and balance in one dependable place.</h1>
        <p>Keep daily collections organised, issue accountable receipts, and understand what the school is owed without adding complexity to the work.</p>
      </div>
      <footer>Secure access powered by Supabase</footer>
    </section>

    <section className="auth-panel">
      <div className="auth-card">
        <div className="auth-heading">
          <span>{isLogin ? 'Welcome back' : 'Create your account'}</span>
          <h2>{isLogin ? 'Sign in to your workspace' : 'Start using HarambeeOne'}</h2>
          <p>{isLogin ? 'Use your work email to continue.' : 'First secure your account, then configure the school levels and classes.'}</p>
        </div>

        {error && <div className="auth-message error" role="alert">{error}</div>}
        {notice && <div className="auth-message success" role="status">{notice}</div>}

        <button className="google-button" type="button" onClick={continueWithGoogle} disabled={googleBusy || busy}>
          {googleBusy ? <LoaderCircle className="spin" size={18} /> : <GoogleLogo />}
          Continue with Google
        </button>
        <div className="auth-divider"><span>or use email</span></div>

        <form className="auth-form" onSubmit={submit}>
          {!isLogin && <label>Full name<input name="fullName" autoComplete="name" required placeholder="Your full name" /></label>}
          <label>Email address<div className="auth-input"><Mail size={17} /><input name="email" type="email" autoComplete="email" required placeholder="name@school.ac.ug" /></div></label>
          <label>Password<div className="auth-input"><LockKeyhole size={17} /><input name="password" type={showPassword ? 'text' : 'password'} autoComplete={isLogin ? 'current-password' : 'new-password'} minLength={isLogin ? 6 : 10} required placeholder={isLogin ? 'Your password' : '10+ characters, including a number'} /><button type="button" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>{!isLogin && <small className="password-guidance">Use 10 or more characters with at least one letter and one number.</small>}</label>
          {!isLogin && <label>Confirm password<input name="confirmation" type={showPassword ? 'text' : 'password'} autoComplete="new-password" minLength={10} required placeholder="Repeat your password" /></label>}
          <button className="auth-submit" disabled={busy || googleBusy}>{busy && <LoaderCircle className="spin" size={18} />}{isLogin ? 'Sign in' : 'Create account'}</button>
        </form>

        {isLogin && <p className="auth-recovery"><Link href="/forgot-password">Forgot your password?</Link></p>}
        <p className="auth-switch">{isLogin ? 'New to HarambeeOne?' : 'Already have an account?'} <Link href={isLogin ? '/signup' : '/login'}>{isLogin ? 'Create an account' : 'Sign in'}</Link></p>
        <p className="auth-terms">By continuing, you agree to protect learner and financial information entrusted to your account.</p>
      </div>
    </section>
  </main>;
}
