'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Download, FileSpreadsheet, Printer, RefreshCw } from 'lucide-react';
import { MetricCard, PageHeader, SectionHeader, Status } from '@/components/ui';
import { clientFetch as fetch } from '@/lib/api/client';
import { getSelectedPeriod, type AcademicPeriod } from '@/lib/period';
import { getPrimarySchool, type School } from '@/lib/school';

const API = '/api/backend';
type ReportOption = { key:string; title:string; description:string };
type StreamOption = { id:string; name:string };
type ClassOption = { id:string; name:string; streams:StreamOption[] };
type Catalog = { reports:ReportOption[]; classes:ClassOption[] };
type Column = { key:string; label:string; format:'text'|'money'|'number'|'date'|'status' };
type Metric = { label:string; value:string|number; format:'money'|'number'; note?:string };
type Report = { report_type:string; title:string; description:string; start_date:string; end_date:string; generated_at:string; columns:Column[]; rows:Record<string,string|number|null>[]; metrics:Metric[]; row_count:number; note?:string|null };

const money = (value:string|number|null|undefined) => `UGX ${Number(value ?? 0).toLocaleString('en-UG', {maximumFractionDigits:0})}`;
const channels = [['cash','Cash'],['bank_transfer','Bank transfer'],['mobile_money','Mobile money'],['schoolpay','SchoolPay'],['card','Card'],['other','Other']];
function displayValue(column:Column, value:string|number|null) {
  if (column.format === 'money') return money(value);
  if (column.format === 'number') return Number(value ?? 0).toLocaleString('en-UG');
  if (column.format === 'date' && value) return new Date(`${String(value)}T00:00:00`).toLocaleDateString('en-UG');
  return value === null || value === '' ? '—' : String(value);
}

export default function ReportsClient() {
  const [school,setSchool] = useState<School|null>(null), [period,setPeriod] = useState<AcademicPeriod|null>(null);
  const [catalog,setCatalog] = useState<Catalog|null>(null), [reportType,setReportType] = useState('collections_daily');
  const [report,setReport] = useState<Report|null>(null), [start,setStart] = useState(''), [end,setEnd] = useState('');
  const [classId,setClassId] = useState(''), [streamId,setStreamId] = useState(''), [channel,setChannel] = useState('');
  const [loading,setLoading] = useState(true), [exporting,setExporting] = useState(false), [error,setError] = useState('');

  const reportUrl = useCallback((kind:string, exportCsv=false) => {
    if (!school || !period) return '';
    const params = new URLSearchParams({school_id:school.id,period_id:period.id,start_date:start,end_date:end});
    if (classId) params.set('class_id',classId); if (streamId) params.set('stream_id',streamId); if (channel) params.set('channel',channel);
    return `${API}/api/v1/reports/centre/${kind}${exportCsv ? '/export.csv' : ''}?${params}`;
  },[channel,classId,end,period,school,start,streamId]);

  const loadReport = useCallback(async (kind:string) => {
    const url = reportUrl(kind); if (!url) return;
    setLoading(true); setError('');
    try {
      const response = await fetch(url,{cache:'no-store'});
      const body = await response.json().catch(() => null) as Report|{detail?:string}|null;
      if (!response.ok) throw new Error((body as {detail?:string}|null)?.detail ?? 'The report could not be generated.');
      setReport(body as Report);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The report could not be generated.'); setReport(null); }
    finally { setLoading(false); }
  },[reportUrl]);

  useEffect(() => {
    Promise.all([getPrimarySchool(),getSelectedPeriod()]).then(async ([currentSchool,currentPeriod]) => {
      setSchool(currentSchool); setPeriod(currentPeriod); setStart(currentPeriod.opening_date); setEnd(currentPeriod.closing_date);
      const response = await fetch(`${API}/api/v1/reports/centre?school_id=${currentSchool.id}`,{cache:'no-store'});
      const body = await response.json().catch(() => null) as Catalog|{detail?:string}|null;
      if (!response.ok) throw new Error((body as {detail?:string}|null)?.detail ?? 'Report options could not be loaded.');
      setCatalog(body as Catalog);
    }).catch(reason => { setError(reason instanceof Error ? reason.message : 'The report centre is unavailable.'); setLoading(false); });
  },[]);
  useEffect(() => { if (school && period && start && end && catalog) void loadReport(reportType); },[catalog,end,loadReport,period,reportType,school,start]);
  const selectedClass = useMemo(() => catalog?.classes.find(item => item.id === classId) ?? null,[catalog,classId]);
  function generate(event:FormEvent) { event.preventDefault(); void loadReport(reportType); }
  async function exportCsv() {
    const url=reportUrl(reportType,true); if (!url || !report) return; setExporting(true); setError('');
    try {
      const response=await fetch(url,{cache:'no-store'}); if (!response.ok) { const body=await response.json().catch(()=>null) as {detail?:string}|null; throw new Error(body?.detail ?? 'The CSV export could not be prepared.'); }
      const blobUrl=URL.createObjectURL(await response.blob()), link=document.createElement('a'); link.href=blobUrl; link.download=`harambeeone-${report.report_type}-${report.start_date}-${report.end_date}.csv`; link.click(); URL.revokeObjectURL(blobUrl);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The CSV export could not be prepared.'); }
    finally { setExporting(false); }
  }

  return <div className="report-centre"><PageHeader eyebrow="Finance · Management reporting" title="Bursar report centre" description="Operational and control reports calculated from the same learner ledger, payment, reconciliation and cash-up records." actions={<div className="page-actions no-print"><button className="btn" disabled={!report||exporting} onClick={()=>void exportCsv()}><Download size={16}/>{exporting?'Preparing…':'Download CSV'}</button><button className="btn primary" disabled={!report} onClick={()=>window.print()}><Printer size={16}/>Print report</button></div>}/>
    {error&&<div className="form-error page-error" role="alert">{error}</div>}
    <form className="panel report-control no-print" onSubmit={generate}><div className="report-picker">
      <label><span>Report</span><select className="select-control" value={reportType} onChange={event=>setReportType(event.target.value)}>{catalog?.reports.map(item=><option value={item.key} key={item.key}>{item.title}</option>)}</select></label>
      <label><span>From</span><input className="select-control" type="date" value={start} max={end} onChange={event=>setStart(event.target.value)} required/></label>
      <label><span>To</span><input className="select-control" type="date" value={end} min={start} onChange={event=>setEnd(event.target.value)} required/></label>
      <label><span>Class</span><select className="select-control" value={classId} onChange={event=>{setClassId(event.target.value);setStreamId('');}}><option value="">All classes</option>{catalog?.classes.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      <label><span>Stream</span><select className="select-control" value={streamId} disabled={!selectedClass} onChange={event=>setStreamId(event.target.value)}><option value="">All streams</option>{selectedClass?.streams.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      <label><span>Channel</span><select className="select-control" value={channel} onChange={event=>setChannel(event.target.value)}><option value="">All channels</option>{channels.map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
      <button className="btn primary" type="submit" disabled={loading}><RefreshCw size={15}/>{loading?'Generating…':'Generate'}</button>
    </div></form>
    {report&&<><header className="report-print-heading"><small>{school?.name} · {period?.academic_year_name} · {period?.name}</small><h2>{report.title}</h2><p>{report.description}</p><time>{new Date(report.generated_at).toLocaleString('en-UG')}</time></header>
      <section className="metric-grid report-metrics">{report.metrics.slice(0,4).map((metric,index)=><MetricCard key={metric.label} icon={FileSpreadsheet} label={metric.label} value={metric.format==='money'?money(metric.value):Number(metric.value).toLocaleString('en-UG')} note={metric.note||`${report.start_date} to ${report.end_date}`} tone={index===0?'green':index===2?'amber':index===3?'blue':undefined}/>)}</section>
      {report.note&&<div className="notice report-note">{report.note}</div>}
      <section className="panel report-register"><SectionHeader title={report.title} subtitle={`${report.row_count.toLocaleString('en-UG')} rows · ${report.start_date} to ${report.end_date}`}/><div className="table-wrap"><table className="data-table report-table"><thead><tr>{report.columns.map(column=><th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{report.rows.map((row,index)=><tr key={`${report.report_type}-${index}`}>{report.columns.map(column=><td className={column.format==='money'?'amount':''} key={column.key}>{column.format==='status'?<Status tone={String(row[column.key]).toLowerCase().includes('reconciled')||String(row[column.key]).toLowerCase().includes('signed')?'success':'warning'}>{displayValue(column,row[column.key])}</Status>:displayValue(column,row[column.key])}</td>)}</tr>)}{!loading&&!report.rows.length&&<tr><td colSpan={report.columns.length}><div className="empty-register"><FileSpreadsheet/><strong>No records for this report</strong><span>Change the filters or period, then generate the report again.</span></div></td></tr>}</tbody></table></div></section>
    </>}
    {loading&&!report&&<div className="panel report-loading"><RefreshCw size={20}/><strong>Preparing the report</strong><span>Calculating authoritative totals…</span></div>}
  </div>;
}
