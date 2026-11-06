import './globals.css';
import './human.css';
import './auth.css';
import './support.css';
import './portal.css';
import './guardian.css';
import './donor.css';
import './notifications.css';
import './outcomes.css';
import './donor-timeline.css';
import './assistant.css';
import './payment-desk.css';
import './receipt-controls.css';
import './reconciliation-controls.css';
import './arrears/arrears.css';
import AppShell from '@/components/AppShell';

// The root layout owns global styling, metadata, and the shared shell.
// Authentication and role-aware navigation remain in session-aware components.
export const metadata = { title: 'HarambeeOne', description: 'School finance and programmable education funding', icons: { icon: '/harambeeone-logo.png' } };
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en" suppressHydrationWarning><body><AppShell>{children}</AppShell></body></html>}
