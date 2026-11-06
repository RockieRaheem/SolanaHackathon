import Link from 'next/link';

export default function AuthErrorPage() {
  return <main className="auth-state"><div><h1>Sign-in could not be completed</h1><p>The link may have expired or already been used.</p><Link className="auth-submit" href="/login">Return to sign in</Link></div></main>;
}
