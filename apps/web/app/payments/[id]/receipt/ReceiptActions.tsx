'use client';

import { useState } from 'react';
import { LoaderCircle, Printer } from 'lucide-react';
import { clientFetch as fetch } from '@/lib/api/client';

export default function ReceiptActions({paymentId,reissueCount}:{paymentId:string;reissueCount:number}){
  const [printed,setPrinted]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function print(){
    if(reissueCount===0&&!printed){setPrinted(true);window.print();return;}
    const reason=window.prompt('Why is another copy of this official receipt required?');
    if(!reason)return;
    if(reason.trim().length<5){setError('Enter a clear reprint reason of at least 5 characters.');return;}
    setBusy(true);setError('');
    try{const response=await fetch(`/api/backend/api/v1/payments/${paymentId}/reissues`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'The receipt reprint could not be recorded.');setPrinted(true);window.print();}catch(reason){setError(reason instanceof Error?reason.message:'The receipt reprint could not be recorded.');}finally{setBusy(false);}
  }
  return <div className="receipt-action-group no-print"><button className="btn primary" disabled={busy} onClick={()=>void print()}>{busy?<LoaderCircle className="spin" size={16}/>:<Printer size={16}/>}Print {reissueCount||printed?'another copy':'receipt'}</button>{error&&<span role="alert">{error}</span>}</div>;
}
