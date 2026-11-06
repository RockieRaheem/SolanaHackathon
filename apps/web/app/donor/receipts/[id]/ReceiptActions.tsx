'use client';

import { Download, Printer } from 'lucide-react';

export default function ReceiptActions({receiptNo}:{receiptNo:string}){
  function download(){const text=document.getElementById('official-donor-receipt')?.innerText??'';const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`${receiptNo}.txt`;anchor.click();URL.revokeObjectURL(url)}
  return <div className="receipt-actions"><button className="btn" onClick={()=>window.print()}><Printer size={15}/>Print</button><button className="btn primary" onClick={download}><Download size={15}/>Download</button></div>;
}
