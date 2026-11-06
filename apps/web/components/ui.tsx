import type { LucideIcon } from 'lucide-react';
import { ArrowUpRight, ChevronRight, RotateCcw, Search } from 'lucide-react';

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: React.ReactNode }) {
  return <header className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="page-actions">{actions}</div>}</header>;
}
export function MetricCard({ label, value, note, icon: Icon, tone = 'navy', trend }: { label: string; value: string; note: string; icon: LucideIcon; tone?: 'navy'|'green'|'amber'|'red'|'blue'; trend?: string | { value: string; up?: boolean } }) {
  const trendLabel = typeof trend === 'string' ? trend : trend?.value;
  return <article className={`metric-card tone-${tone}`}><div className="metric-top"><span className="metric-icon"><Icon size={19} /></span>{trendLabel && <span className="trend"><ArrowUpRight size={13}/> {trendLabel}</span>}</div><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong><span className="metric-note">{note}</span></article>;
}
export function Status({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) { return <span className={`status status-${tone}`}><i />{children}</span>; }
export function SectionHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) { return <div className="section-header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{typeof action === 'string' ? <button className="text-button">{action}<ChevronRight size={15}/></button> : action}</div>; }

export function FilterSearch({ value, onChange, placeholder = 'Search records', label = 'Search records' }: { value: string; onChange: (value: string) => void; placeholder?: string; label?: string }) {
  return <label className="filter-input"><Search size={15} aria-hidden="true"/><span className="sr-only">{label}</span><input type="search" value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder}/></label>;
}

export function RegisterFilters({ children, shown, total, active = false, onReset }: { children?: React.ReactNode; shown: number; total: number; active?: boolean; onReset?: () => void }) {
  return <div className="filter-bar register-filters">{children}<div className="filter-summary" aria-live="polite"><strong>{shown}</strong><span>{shown === total ? 'records' : `of ${total} records`}</span></div>{active && onReset && <button type="button" className="filter-reset" onClick={onReset}><RotateCcw size={13}/>Reset</button>}</div>;
}
