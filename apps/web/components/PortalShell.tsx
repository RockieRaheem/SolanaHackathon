'use client';

import Image from 'next/image';
import Link from 'next/link';
import { Bot, LogOut, PanelsTopLeft } from 'lucide-react';
import { signOutAndRedirect } from '@/lib/sign-out';
import NotificationCenter from '@/components/NotificationCenter';

export default function PortalShell({
  label,
  children,
}:{
  label:string;
  children:React.ReactNode;
}) {
  async function signOut() {
    await signOutAndRedirect();
  }
  return <div className="portal-page">
    <header className="portal-header">
      <Link href="/workspace" className="portal-brand"><Image src="/harambeeone-logo.png" width={38} height={38} alt=""/><span><strong>HarambeeOne</strong><small>{label}</small></span></Link>
      <nav>{label === 'Guardian workspace' && <><Link href="/guardian/outcomes">Outcome updates</Link><Link href="/guardian/assistant"><Bot size={16}/>Gemma assistant</Link></>}{label === 'Donor workspace' && <><Link href="/donor/timeline">Campaign timeline</Link><Link href="/donor/assistant"><Bot size={16}/>Gemma assistant</Link></>}<Link href="/workspace"><PanelsTopLeft size={16}/>Workspaces</Link><button onClick={signOut}><LogOut size={16}/>Sign out</button></nav>
    </header>
    <main className="portal-main"><NotificationCenter compact/>{children}</main>
  </div>;
}
