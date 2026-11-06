import Link from 'next/link';
import { redirect } from 'next/navigation';
import { Building2, HandHeart, HeartHandshake } from 'lucide-react';
import PortalShell from '@/components/PortalShell';
import { authorizedBackendFetch } from '@/lib/api/server';

type Portal = {type:'school'|'guardian'|'donor';label:string;detail:string;href:string;school_id?:string};
type Context = {display_name:string;preferred_workspace:string|null;portals:Portal[]};
const icons = {school:Building2, guardian:HeartHandshake, donor:HandHeart};

export default async function WorkspacePage() {
  const response = await authorizedBackendFetch('/api/v1/me/portals');
  if (response.status === 401) redirect('/login?error=session_expired&next=/workspace');
  if (!response.ok) return <PortalShell label="Account access">
    <div className="portal-empty" role="alert">
      <Building2/>
      <h2>We could not load your workspaces</h2>
      <p>Your account is safe. The service may be temporarily unavailable.</p>
      <Link className="btn primary" href="/workspace">Try again</Link>
    </div>
  </PortalShell>;
  const context:Context = await response.json();
  const preferred = context.portals.find(item => item.type === context.preferred_workspace);
  if (preferred) redirect(preferred.href);
  if (context.portals.length === 1) redirect(context.portals[0].href);
  if (!context.portals.length) redirect('/welcome');
  return <PortalShell label="Choose workspace">
    <section className="portal-intro"><span>Signed in as {context.display_name}</span><h1>Where would you like to work?</h1><p>Each workspace shows only the information and actions assigned to that role.</p></section>
    <div className="workspace-cards">{context.portals.map(item => {const Icon=icons[item.type];return <Link href={item.href} key={`${item.type}-${item.label}`}><Icon/><span><strong>{item.label}</strong><small>{item.detail}</small></span></Link>;})}</div>
  </PortalShell>;
}
