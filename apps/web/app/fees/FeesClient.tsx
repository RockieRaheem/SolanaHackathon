'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Award, CalendarClock, CheckCircle2, Plus, ReceiptText, Tags, UserRoundCog, X } from 'lucide-react';
import { PageHeader, SectionHeader, Status } from '@/components/ui';
import { getPrimarySchool, type School } from '@/lib/school';
import { AcademicPeriod, getSelectedPeriod } from '@/lib/period';
import { clientFetch as fetch } from '@/lib/api/client';

const API = '/api/backend';
type Stream = { id:string; name:string };
type Group = { id:string; name:string; streams:Stream[] };
type Student = { id:string; admission_no:string; full_name:string; class_name:string; stream_name:string|null };
type Category = { id:string; name:string; code:string; is_required:boolean; priority:number };
type Installment = { id?:string; name:string; calculation_type:'fixed'|'percentage'; amount:string; percentage:string; due_date:string; sort_order:number };
type Plan = { id:string; class_id:string; stream_id:string|null; name:string; academic_year:number; term:number; currency:string; total_amount:string; target_type:'cohort'|'selected'; boarding_status:string|null; status:'draft'|'published'; is_general:boolean; selected_learner_count:number; installments:Installment[] };
type RequirementSummary = { id:string; name:string; status:'draft'|'published'; classes:{id:string;name:string}[] };
type Adjustment = { id:string; student_name:string; admission_no:string; category_name:string|null; adjustment_type:string; amount:string; description:string; reason:string; status:'draft'|'published' };
type PreviewLine = { id:string; name:string; learner_count:number; amount_per_learner:string; total:string; type?:string };
type Preview = { preview_token:string; can_publish:boolean; summary:{learner_count:number;fee_assignment_count:number;requirement_assignment_count:number;adjustment_count:number;charge_total:string;credit_total:string;net_total:string};fee_plans:PreviewLine[];requirements:PreviewLine[];adjustments:{id:string;student_name:string;type:string;description:string;amount:string}[];conflicts:{student_id:string;admission_no:string;student_name:string;reason:string;plans:string[]}[];exclusions:{student_id:string;admission_no:string;student_name:string;reason:string}[] };

const blankInstallment = (order:number):Installment => ({name:`Installment ${order}`,calculation_type:'percentage',amount:'',percentage:'',due_date:'',sort_order:order});
const money = (value:string|number) => `UGX ${Number(value).toLocaleString('en-UG',{maximumFractionDigits:2})}`;

export default function FeesClient() {
  const [school,setSchool]=useState<School|null>(null),[period,setPeriod]=useState<AcademicPeriod|null>(null);
  const [groups,setGroups]=useState<Group[]>([]),[students,setStudents]=useState<Student[]>([]),[categories,setCategories]=useState<Category[]>([]),[plans,setPlans]=useState<Plan[]>([]),[requirements,setRequirements]=useState<RequirementSummary[]>([]),[adjustments,setAdjustments]=useState<Adjustment[]>([]);
  const [preview,setPreview]=useState<Preview|null>(null),[idempotencyKey,setIdempotencyKey]=useState('');
  const [categoryOpen,setCategoryOpen]=useState(false),[planOpen,setPlanOpen]=useState(false),[adjustmentOpen,setAdjustmentOpen]=useState(false);
  const [planScope,setPlanScope]=useState<'general'|'targeted'>('general'),[adjustmentMode,setAdjustmentMode]=useState<'adjustment'|'scholarship'>('adjustment');
  const [targetType,setTargetType]=useState<'cohort'|'selected'>('cohort'),[classId,setClassId]=useState(''),[installments,setInstallments]=useState<Installment[]>([{...blankInstallment(1),name:'Full term',percentage:'100'}]);
  const [error,setError]=useState(''),[planError,setPlanError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
  const [statusFilter,setStatusFilter]=useState('all');

  const load = useCallback(async (currentSchool:string,currentPeriod:string) => {
    const query=`school_id=${currentSchool}&period_id=${currentPeriod}`;
    const responses=await Promise.all([
      fetch(`${API}/api/v1/fee-categories?school_id=${currentSchool}`),
      fetch(`${API}/api/v1/fee-structures?${query}`),
      fetch(`${API}/api/v1/schools/${currentSchool}/classes`),
      fetch(`${API}/api/v1/students?${query}`),
      fetch(`${API}/api/v1/billing/adjustments?${query}`),
      fetch(`${API}/api/v1/billing/preview?${query}`),
      fetch(`${API}/api/v1/requirements?${query}`),
    ]);
    if(responses.some(response=>!response.ok)) throw new Error('Billing workspace could not be loaded.');
    const [categoryRows,planRows,classRows,studentRows,adjustmentRows,previewRow,requirementRows]=await Promise.all(responses.map(response=>response.json()));
    setCategories(categoryRows);setPlans(planRows);setGroups(classRows);setStudents(studentRows.items);setAdjustments(adjustmentRows);setPreview(previewRow);setRequirements(requirementRows);setClassId(current=>current||classRows[0]?.id||'');setIdempotencyKey(crypto.randomUUID());
  },[]);

  useEffect(()=>{Promise.all([getPrimarySchool(),getSelectedPeriod()]).then(([currentSchool,currentPeriod])=>{setSchool(currentSchool);setPeriod(currentPeriod);return load(currentSchool.id,currentPeriod.id)}).catch(reason=>setError(reason instanceof Error?reason.message:'Billing workspace is unavailable.')).finally(()=>setLoading(false))},[load]);
  const reload=async(message?:string)=>{if(!school||!period)return;await load(school.id,period.id);if(message)setNotice(message)};
  const selectedGroup=groups.find(group=>group.id===classId);
  const visiblePlans=useMemo(()=>plans.filter(plan=>plan.class_id===classId&&(statusFilter==='all'||plan.status===statusFilter)),[classId,plans,statusFilter]);
  const classStudents=students.filter(student=>student.class_name===selectedGroup?.name);
  const classRequirements=requirements.filter(item=>item.classes.some(group=>group.id===classId));
  const generalPlan=plans.find(plan=>plan.class_id===classId&&plan.is_general&&plan.status==='published')??plans.find(plan=>plan.class_id===classId&&plan.is_general);
  const openPlan=()=>{if(!classId)return;setPlanError('');setPlanScope(generalPlan?'targeted':'general');setTargetType('cohort');setInstallments([{...blankInstallment(1),name:'Full term',percentage:'100',due_date:period?.due_date??''}]);setPlanOpen(true)};

  async function addCategory(event:FormEvent<HTMLFormElement>){event.preventDefault();if(!school)return;setBusy(true);setError('');const form=new FormData(event.currentTarget);const name=String(form.get('name')||'').trim();const code=(name.replace(/[^A-Za-z0-9]/g,'').slice(0,10)||'FEE').toUpperCase();try{const response=await fetch(`${API}/api/v1/fee-categories`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({school_id:school.id,name,code,category_type:form.get('type'),is_required:true,is_recurring:true,priority:categories.length+1})});const body=await response.json();if(!response.ok)throw new Error(body.detail??'Category could not be saved.');setCategoryOpen(false);await reload('Fee category created.')}catch(reason){setError(reason instanceof Error?reason.message:'Category could not be saved.')}finally{setBusy(false)}}

  async function addPlan(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!school||!period||!selectedGroup)return;
    const formElement=event.currentTarget;
    const form=new FormData(formElement);
    const isGeneral=planScope==='general';
    setError('');setPlanError('');

    const items=categories.map(category=>{
      const raw=String(form.get(`category-${category.id}`)||'').trim();
      const amount=Number(raw);
      return {category_id:category.id,amount,raw};
    }).filter(item=>item.raw!=='');
    if(!items.length){
      setPlanError('Enter an amount greater than zero for at least one fee category.');
      formElement.scrollTo({top:0,behavior:'smooth'});
      return;
    }
    if(items.some(item=>!Number.isFinite(item.amount)||item.amount<=0||!Number.isSafeInteger(Math.round(item.amount*100)))){
      setPlanError('Every entered category amount must be a valid positive UGX amount with no more than two decimal places.');
      formElement.scrollTo({top:0,behavior:'smooth'});
      return;
    }
    const totalCents=items.reduce((sum,item)=>sum+Math.round(item.amount*100),0);
    const rules=installments.map((item,index)=>({
      name:item.name.trim(),calculation_type:item.calculation_type,
      amount:item.calculation_type==='fixed'?Number(item.amount):null,
      percentage:item.calculation_type==='percentage'?Number(item.percentage):null,
      due_date:item.due_date,sort_order:index+1,
    }));
    if(rules.some(item=>!item.name||!item.due_date)){
      setPlanError('Give every installment a name and due date.');
      formElement.scrollTo({top:0,behavior:'smooth'});
      return;
    }
    const invalidRule=rules.some(item=>{
      const value=item.calculation_type==='fixed'?item.amount:item.percentage;
      return value===null||!Number.isFinite(value)||value<=0;
    });
    if(invalidRule){
      setPlanError('Every installment amount or percentage must be greater than zero.');
      formElement.scrollTo({top:0,behavior:'smooth'});
      return;
    }
    const installmentCents=rules.reduce((sum,item)=>sum+(
      item.calculation_type==='fixed'
        ?Math.round((item.amount??0)*100)
        :Math.round(totalCents*(item.percentage??0)/100)
    ),0);
    if(installmentCents!==totalCents){
      setPlanError(`The installment schedule must equal ${money(totalCents/100)}. It currently equals ${money(installmentCents/100)}.`);
      formElement.scrollTo({top:0,behavior:'smooth'});
      return;
    }
    if(!isGeneral&&targetType==='selected'&&!form.getAll('student_ids').length){
      setPlanError('Select at least one learner for this targeted fee.');
      formElement.scrollTo({top:0,behavior:'smooth'});
      return;
    }

    setBusy(true);
    try{
      const response=await fetch(`${API}/api/v1/fee-plans`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          school_id:school.id,period_id:period.id,class_id:classId,
          stream_id:isGeneral?null:form.get('stream_id')||null,
          name:isGeneral?`${selectedGroup.name} general fees · ${period.name}`:String(form.get('name')||`${selectedGroup.name} targeted fee`),
          academic_year:period.academic_year,term:period.sequence,currency:'UGX',
          target_type:isGeneral?'cohort':targetType,
          boarding_status:isGeneral?null:form.get('boarding_status')||null,
          student_ids:!isGeneral&&targetType==='selected'?form.getAll('student_ids'):[],
          items:items.map(({category_id,amount})=>({category_id,amount})),installments:rules,
        }),
      });
      const body=await response.json().catch(()=>({}));
      if(!response.ok){
        const detail=Array.isArray(body.detail)
          ?body.detail.map((item:{loc?:Array<string|number>;msg?:string})=>{
            const field=(item.loc||[]).filter(value=>value!=='body').join(' › ');
            return `${field?field+': ':''}${item.msg||'Invalid value'}`;
          }).join(' · ')
          :body.detail;
        throw new Error(detail||'Fee plan could not be saved.');
      }
      setPlanOpen(false);setPlanScope('general');setTargetType('cohort');setPlanError('');
      const successMessage=isGeneral?'General class fee saved as a draft. Publish the preview to activate automatic assignment.':'Draft fee plan created. Review the billing preview before publishing.';
      try{await reload(successMessage)}catch{
        setNotice(successMessage);
        setError('The fee plan was saved, but the billing workspace could not refresh. Reload the page to see the latest figures.');
      }
      requestAnimationFrame(()=>document.getElementById('billing-publication-preview')?.scrollIntoView({behavior:'smooth',block:'start'}));
    }catch(reason){
      setPlanError(reason instanceof Error?reason.message:'Fee plan could not be saved.');
      formElement.scrollTo({top:0,behavior:'smooth'});
    }finally{setBusy(false)}
  }

  async function addAdjustment(event:FormEvent<HTMLFormElement>){event.preventDefault();if(!school||!period)return;setBusy(true);setError('');const form=new FormData(event.currentTarget);try{const response=await fetch(`${API}/api/v1/billing/adjustments`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({school_id:school.id,period_id:period.id,student_id:form.get('student_id'),category_id:form.get('category_id')||null,adjustment_type:adjustmentMode==='scholarship'?'sponsorship_credit':form.get('adjustment_type'),amount:Number(form.get('amount')),description:form.get('description'),reason:form.get('reason')})});const body=await response.json();if(!response.ok){const detail=Array.isArray(body.detail)?body.detail[0]?.msg:body.detail;throw new Error(detail||'Adjustment could not be saved.')}setAdjustmentOpen(false);await reload(adjustmentMode==='scholarship'?'Scholarship added to the controlled billing preview.':'Learner adjustment added to the draft preview.')}catch(reason){setError(reason instanceof Error?reason.message:'Adjustment could not be saved.')}finally{setBusy(false)}}

  const openAdjustment=(mode:'adjustment'|'scholarship')=>{setAdjustmentMode(mode);setAdjustmentOpen(true)};

  async function removeAdjustment(id:string){if(!window.confirm('Remove this draft adjustment?'))return;const response=await fetch(`${API}/api/v1/billing/adjustments/${id}`,{method:'DELETE'});if(!response.ok){const body=await response.json();return setError(body.detail??'Adjustment could not be removed.')}await reload('Draft adjustment removed.')}

  async function removePlan(plan:Plan){if(plan.status!=='draft'||!window.confirm(`Remove the draft fee plan "${plan.name}"?`))return;const response=await fetch(`${API}/api/v1/fee-plans/${plan.id}`,{method:'DELETE'});if(!response.ok){const body=await response.json();return setError(body.detail??'Fee plan could not be removed.')}await reload('Draft fee plan removed.')}

  async function publish(){if(!school||!period||!preview||!preview.can_publish)return;if(!window.confirm(`Publish ${money(preview.summary.net_total)} to ${preview.summary.learner_count} learner accounts? Posted entries cannot be edited or deleted.`))return;setBusy(true);setError('');try{const response=await fetch(`${API}/api/v1/billing/publish`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({school_id:school.id,period_id:period.id,preview_token:preview.preview_token,idempotency_key:idempotencyKey})});const body=await response.json();if(!response.ok)throw new Error(body.detail??'Billing could not be published.');await reload(`Billing published successfully: ${money(body.net_total)} across ${body.learner_count} learners.`)}catch(reason){setError(reason instanceof Error?reason.message:'Billing could not be published.')}finally{setBusy(false)}}

  const updateInstallment=(index:number,key:keyof Installment,value:string)=>setInstallments(rows=>rows.map((row,rowIndex)=>rowIndex===index?{...row,[key]:value}:row));
  if(loading)return <div className="page-state"><CalendarClock className="spin"/><h1>Preparing term billing</h1><p>Loading learners, plans and draft obligations…</p></div>;
  return <>
    <PageHeader eyebrow="Bursar · Class billing" title="Fees & requirements" description="Choose a class once, configure its term obligations, then review and publish one controlled billing batch." actions={<button className="btn primary" onClick={openPlan} disabled={!classId||!categories.length}><Plus size={15}/>Set class fee</button>}/>
    {error&&<div className="form-error page-error">{error}<button onClick={()=>setError('')}><X size={15}/></button></div>}{notice&&<div className="success-banner"><CheckCircle2 size={16}/>{notice}<button onClick={()=>setNotice('')}><X size={15}/></button></div>}

    <section className="panel class-billing-workspace">
      <SectionHeader title="Class billing setup" subtitle="Select a class to see only the fee and requirements that apply to it." action={<div className="row-actions"><button className="text-button" onClick={()=>setCategoryOpen(true)}><Tags size={14}/>Manage fee categories</button><Link className="btn soft" href={classId?('/requirements?class='+classId+'&create=1'):'/requirements'}><Plus size={14}/>Add requirement</Link></div>}/>
      <div className="class-scope-list" role="tablist" aria-label="Classes">
        {groups.map(group=>{const groupPlan=plans.find(plan=>plan.class_id===group.id&&plan.is_general);const requirementCount=requirements.filter(item=>item.classes.some(value=>value.id===group.id)).length;return <button type="button" role="tab" aria-selected={classId===group.id} className={classId===group.id?'class-scope-card active':'class-scope-card'} key={group.id} onClick={()=>setClassId(group.id)}><strong>{group.name}</strong><span>{groupPlan?money(groupPlan.total_amount):'Fee not set'}</span><small>{requirementCount} requirement{requirementCount===1?'':'s'}</small></button>})}
      </div>
      {selectedGroup&&<div className="class-workspace-summary">
        <div><span>Selected class</span><strong>{selectedGroup.name}</strong><small>{classStudents.length} active learner{classStudents.length===1?'':'s'}</small></div>
        <div><span>General fee</span><strong>{generalPlan?money(generalPlan.total_amount):'Not configured'}</strong><small>{generalPlan?generalPlan.status:'Create one fee for the whole class'}</small></div>
        <div><span>Requirements</span><strong>{classRequirements.length}</strong><small>{classRequirements.filter(item=>item.status==='draft').length} awaiting publication</small></div>
        <div className="class-workspace-actions"><button className="btn primary" onClick={openPlan} disabled={!categories.length}>{generalPlan?'Add targeted fee':'Set general fee'}</button><Link className="btn" href={'/requirements?class='+classId+'&create=1'}>Add requirement</Link></div>
      </div>}
      {!categories.length&&<div className="inline-guidance"><AlertTriangle size={16}/><span>Create at least one fee category before setting a class fee.</span><button className="text-button" onClick={()=>setCategoryOpen(true)}>Create category</button></div>}
      <div className="billing-flow"><span><b>1</b>Choose class</span><span><b>2</b>Set fee & requirements</span><span><b>3</b>Review preview</span><span><b>4</b>Publish to learners</span></div>
    </section>

    <section id="billing-publication-preview" className="panel billing-preview"><SectionHeader title={`Learner account posting · ${period?.name??''}`} subtitle="Review draft fees and requirements here before they become permanent learner-account entries." action={preview?.can_publish?<Status tone="warning">Not yet posted</Status>:<Status tone="success">Accounts current</Status>}/>
      {preview?.can_publish&&<div className="billing-posting-gate"><AlertTriangle size={20}/><div><strong>These draft charges are not yet on learner accounts</strong><span>Review the figures below, then post {money(preview.summary.net_total)} to {preview.summary.learner_count} learner{preview.summary.learner_count===1?'':'s'}. Posting creates permanent ledger entries.</span></div><button className="btn success" disabled={busy} onClick={publish}>{busy?'Posting…':`Post to ${preview.summary.learner_count} learner account${preview.summary.learner_count===1?'':'s'}`}</button></div>}
      {!preview?.can_publish&&!preview?.conflicts.length&&<div className="empty-register"><CheckCircle2/><strong>No unpublished billing remains</strong><span>Create a plan, requirement or learner adjustment to prepare another controlled batch.</span></div>}
      {preview&&preview.conflicts.length>0&&<div className="billing-warning"><AlertTriangle size={18}/><div><strong>Resolve {preview.conflicts.length} fee-plan conflict{preview.conflicts.length===1?'':'s'} before publishing</strong>{preview.conflicts.map(item=><span key={item.student_id}>{item.student_name} ({item.admission_no}) matches {item.plans.join(' and ')}.</span>)}</div></div>}
      {preview?.can_publish&&<><div className="billing-totals"><div><span>Charges</span><strong>{money(preview.summary.charge_total)}</strong></div><div><span>Credits</span><strong>− {money(preview.summary.credit_total)}</strong></div><div><span>Net posting</span><strong>{money(preview.summary.net_total)}</strong></div></div><div className="table-wrap"><table className="data-table"><thead><tr><th>Source</th><th>Type</th><th>Learners</th><th>Amount each</th><th>Total</th></tr></thead><tbody>{preview.fee_plans.map(item=><tr key={`fee-${item.id}`}><td><strong>{item.name}</strong></td><td>Fee plan</td><td>{item.learner_count}</td><td>{money(item.amount_per_learner)}</td><td className="amount">{money(item.total)}</td></tr>)}{preview.requirements.map(item=><tr key={`requirement-${item.id}`}><td><strong>{item.name}</strong></td><td>{item.type?.replaceAll('_',' ')}</td><td>{item.learner_count}</td><td>{money(item.amount_per_learner)}</td><td className="amount">{money(item.total)}</td></tr>)}{preview.adjustments.map(item=><tr key={`adjustment-${item.id}`}><td className="entity"><strong>{item.description}</strong><small>{item.student_name}</small></td><td>{item.type.replaceAll('_',' ')}</td><td>1</td><td>{money(item.amount)}</td><td className="amount">{item.type==='addition'?'':'− '}{money(item.amount)}</td></tr>)}</tbody></table></div></>}
      {!!preview?.exclusions.length&&<details className="billing-exclusions"><summary>{preview.exclusions.length} enrolled learner{preview.exclusions.length===1?' has':'s have'} no matching fee plan</summary>{preview.exclusions.map(item=><p key={item.student_id}><strong>{item.student_name}</strong> · {item.admission_no} — {item.reason}</p>)}</details>}
    </section>

    <section className="panel class-plan-register">
      <SectionHeader title={(selectedGroup?.name??'Class')+' fee plans'} subtitle="The general fee covers the whole class. Use targeted fees only for genuine exceptions." action={<select className="select-control" value={statusFilter} onChange={event=>setStatusFilter(event.target.value)} aria-label="Plan status"><option value="all">All statuses</option><option value="draft">Draft only</option><option value="published">Published only</option></select>}/>
      <div className="table-wrap"><table className="data-table"><thead><tr><th>Fee</th><th>Who receives it</th><th>Schedule</th><th>Status</th><th>Total</th><th></th></tr></thead><tbody>{visiblePlans.map(plan=><tr key={plan.id}><td className="entity"><strong>{plan.name}</strong><small>{plan.is_general?'Automatic class fee':'Targeted exception'}</small></td><td>{plan.is_general?'Every learner in '+(selectedGroup?.name??'class'):plan.target_type==='selected'?plan.selected_learner_count+' selected learners':[plan.stream_id?selectedGroup?.streams.find(item=>item.id===plan.stream_id)?.name:null,plan.boarding_status?.replace('_',' ')].filter(Boolean).join(' · ')||'Whole class'}</td><td>{plan.installments.length} installment{plan.installments.length===1?'':'s'}</td><td><Status tone={plan.status==='published'?'success':'warning'}>{plan.status}</Status></td><td className="amount">{money(plan.total_amount)}</td><td>{plan.status==='draft'?<button className="text-button" onClick={()=>removePlan(plan)}>Remove</button>:<span className="muted-action">Active</span>}</td></tr>)}{!visiblePlans.length&&<tr><td colSpan={6}><div className="empty-register"><ReceiptText/><strong>No fee configured for this class</strong><span>Set the general fee, add any requirements, then publish them together.</span><button className="btn primary" onClick={openPlan} disabled={!categories.length}>Set class fee</button></div></td></tr>}</tbody></table></div>
    </section>

    <details className="secondary-workflow">
      <summary>Learner-specific scholarships and adjustments <span>{adjustments.length}</span></summary>
      <div className="secondary-workflow-actions"><p>Use these only when one learner needs an approved exception to the class bill.</p><button className="btn" onClick={()=>openAdjustment('adjustment')} disabled={!students.length}><UserRoundCog size={15}/>Add adjustment</button><button className="btn" onClick={()=>openAdjustment('scholarship')} disabled={!students.length}><Award size={15}/>Apply scholarship</button></div>
      <div className="attention-list">{adjustments.map(item=><div className="attention-item billing-adjustment" key={item.id}><div><strong>{item.student_name} · {item.description}</strong><small>{item.adjustment_type.replaceAll('_',' ')} · {item.reason}</small></div><span className="amount">{money(item.amount)}</span><time>{item.status}</time>{item.status==='draft'&&<button className="text-button" onClick={()=>removeAdjustment(item.id)}>Remove</button>}</div>)}{!adjustments.length&&<div className="empty-register">No learner-specific exceptions have been added.</div>}</div>
    </details>
    {categoryOpen&&<div className="modal-backdrop"><section className="modal"><header><div><h2>Add fee category</h2><p>Create a reusable line such as tuition, meals or transport. The system creates the accounting code and order.</p></div><button onClick={()=>setCategoryOpen(false)}><X size={20}/></button></header><form className="modal-form" onSubmit={addCategory}><label>Category name<input name="name" required autoFocus placeholder="Tuition"/></label><label>Category type<select name="type"><option value="tuition">Tuition</option><option value="boarding">Boarding</option><option value="transport">Transport</option><option value="meals">Meals</option><option value="uniform">Uniform</option><option value="other">Other</option></select></label><footer><button type="button" className="btn" onClick={()=>setCategoryOpen(false)}>Cancel</button><button className="btn primary" disabled={busy}>{busy?'Saving…':'Save category'}</button></footer></form></section></div>}

    {planOpen&&<div className="modal-backdrop"><section className="modal registration-modal fee-plan-modal" role="dialog" aria-modal="true" aria-labelledby="fee-plan-title"><header><div><h2 id="fee-plan-title">Configure {selectedGroup?.name}</h2><p>Start with one whole-class fee. Add targeted exceptions only when a stream, residence group or named learner genuinely differs.</p></div><button onClick={()=>setPlanOpen(false)}><X size={20}/></button></header><form className="modal-form" onSubmit={addPlan}>{planError&&<div className="form-error" role="alert"><strong>Fee plan was not saved</strong><span>{planError}</span></div>}<div className="form-section"><div className="class-form-context"><span>Class</span><strong>{selectedGroup?.name}</strong><small>{classStudents.length} active learner{classStudents.length===1?'':'s'} · {period?.name}</small></div><div className="form-grid"><label>Fee coverage<select value={planScope} onChange={event=>setPlanScope(event.target.value as 'general'|'targeted')}><option value="general" disabled={Boolean(generalPlan)}>General fee for the whole class</option><option value="targeted">Special targeted fee</option></select></label>{planScope==='targeted'&&<><label>Fee name<input name="name" required placeholder="Boarding supplement"/></label><label>Target mode<select value={targetType} onChange={event=>setTargetType(event.target.value as 'cohort'|'selected')}><option value="cohort">Every matching learner</option><option value="selected">Selected learners only</option></select></label><label>Stream<select name="stream_id" disabled={!selectedGroup?.streams.length}><option value="">All streams</option>{selectedGroup?.streams.map(stream=><option key={stream.id} value={stream.id}>{stream.name}</option>)}</select></label><label>Residence<select name="boarding_status"><option value="">All residence types</option><option value="day">Day</option><option value="boarding">Boarding</option><option value="half_boarding">Half boarding</option></select></label></>}</div>{planScope==='general'&&<p className="form-help">This becomes the single automatic fee for every current and future learner placed in this class during the term.</p>}{planScope==='targeted'&&targetType==='selected'&&<div className="class-choice-grid learner-choice-grid">{classStudents.map(student=><label key={student.id}><input type="checkbox" name="student_ids" value={student.id}/><span><strong>{student.full_name}</strong><small>{student.admission_no} · {student.stream_name??'No stream'}</small></span></label>)}{!classStudents.length&&<p className="form-help">No active learners are placed in this class for the selected period.</p>}</div>}</div>
      <div className="form-section"><h3>Category amounts</h3><p className="form-help">Enter an amount greater than zero for at least one category. Leave categories that do not apply blank.</p><div className="form-grid">{categories.map(category=><label key={category.id}>{category.name}<input name={`category-${category.id}`} type="number" min="0.01" step="0.01" placeholder="Enter amount"/></label>)}</div></div>
      <div className="form-section"><div className="form-section-title"><div><h3>Installment schedule</h3><p className="form-help">Use any number of fixed amounts or percentages. The combined schedule must equal the plan total.</p></div><button type="button" className="text-button" onClick={()=>setInstallments(rows=>[...rows,blankInstallment(rows.length+1)])}>+ Add installment</button></div>{installments.map((item,index)=><div className="installment-row" key={index}><label>Name<input required value={item.name} onChange={event=>updateInstallment(index,'name',event.target.value)}/></label><label>Calculation<select value={item.calculation_type} onChange={event=>updateInstallment(index,'calculation_type',event.target.value)}><option value="percentage">Percentage</option><option value="fixed">Fixed amount</option></select></label><label>{item.calculation_type==='percentage'?'Percentage':'Amount (UGX)'}<input required type="number" min="0.01" step="0.01" value={item.calculation_type==='percentage'?item.percentage:item.amount} onChange={event=>updateInstallment(index,item.calculation_type==='percentage'?'percentage':'amount',event.target.value)}/></label><label>Due date<input required type="date" value={item.due_date} onChange={event=>updateInstallment(index,'due_date',event.target.value)}/></label>{installments.length>1&&<button type="button" className="remove-guardian" onClick={()=>setInstallments(rows=>rows.filter((_,rowIndex)=>rowIndex!==index))}>Remove</button>}</div>)}</div><footer><button type="button" className="btn" onClick={()=>{setPlanError('');setPlanOpen(false)}}>Cancel</button><button className="btn primary" disabled={busy}>{busy?'Saving…':'Save & review posting'}</button></footer></form></section></div>}

    {adjustmentOpen&&<div className="modal-backdrop"><section className="modal"><header><div><h2>{adjustmentMode==='scholarship'?'Apply scholarship':'Add learner adjustment'}</h2><p>{adjustmentMode==='scholarship'?'Record an approved bursary or scholarship against a learner who already has a posted fee.':'Additions increase a bill; discounts and waivers reduce it.'}</p></div><button onClick={()=>setAdjustmentOpen(false)}><X size={20}/></button></header><form className="modal-form" onSubmit={addAdjustment}><label>Learner<select name="student_id" required><option value="">Select learner</option>{students.map(student=><option key={student.id} value={student.id}>{student.full_name} · {student.admission_no}</option>)}</select></label>{adjustmentMode==='adjustment'&&<label>Adjustment<select name="adjustment_type"><option value="addition">Learner-specific addition</option><option value="discount">Discount</option><option value="waiver">Waiver</option></select></label>}<label>Category<select name="category_id"><option value="">No category</option>{categories.map(category=><option key={category.id} value={category.id}>{category.name}</option>)}</select></label><label>Amount (UGX)<input name="amount" type="number" min="1" step="0.01" required/></label><label>Description<input name="description" required placeholder={adjustmentMode==='scholarship'?'Full-term merit scholarship':'Sibling discount'}/></label><label>{adjustmentMode==='scholarship'?'Approval details':'Reason'}<textarea name="reason" required placeholder={adjustmentMode==='scholarship'?'Scholarship provider, approval reference and conditions':'Approval or policy reason'}/></label>{adjustmentMode==='scholarship'&&<p className="form-help">The scholarship cannot exceed the learner's current balance and becomes an immutable credit only when this billing preview is published.</p>}<footer><button type="button" className="btn" onClick={()=>setAdjustmentOpen(false)}>Cancel</button><button className="btn primary" disabled={busy}>{adjustmentMode==='scholarship'?'Add scholarship to preview':'Add to preview'}</button></footer></form></section></div>}
  </>;
}
