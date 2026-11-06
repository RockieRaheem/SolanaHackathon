'use client';

import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Bot, LogOut, PanelsTopLeft } from 'lucide-react';
import { clearClientResponseCache } from '@/lib/api/client';
import { clearPeriods } from '@/lib/period';
import { clearPrimarySchool } from '@/lib/school';
import { createClient } from '@/lib/supabase/client';
import NotificationCenter from '@/components/NotificationCenter';

export default function PortalShell({
  label,
  children,
}:{
  label:string;
  children:React.ReactNode;
}) {
  const router = useRouter();

  async function signOut() {
    await createClient().auth.signOut();
    clearClientResponseCache();
    clearPeriods();
    clearPrimarySchool();
    router.replace('/login');
    router.refresh();
  }
  return <div className="portal-page">
    <header className="portal-header">
      <Link href="/workspace" className="portal-brand"><Image src="/harambeeone-logo.png" width={38} height={38} alt=""/><span><strong>HarambeeOne</strong><small>{label}</small></span></Link>
      <nav>{label === 'Guardian workspace' && <><Link href="/guardian/outcomes">Outcome updates</Link><Link href="/guardian/assistant"><Bot size={16}/>Gemma assistant</Link></>}{label === 'Donor workspace' && <><Link href="/donor/timeline">Campaign timeline</Link><Link href="/donor/assistant"><Bot size={16}/>Gemma assistant</Link></>}<Link href="/workspace"><PanelsTopLeft size={16}/>Workspaces</Link><button onClick={signOut}><LogOut size={16}/>Sign out</button></nav>
    </header>
    <main className="portal-main"><NotificationCenter compact/>{children}</main>
  </div>;
}
