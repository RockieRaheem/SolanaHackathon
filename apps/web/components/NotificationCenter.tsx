'use client';

import Link from 'next/link';
import { Bell, CheckCheck } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { clientFetch as fetch } from '@/lib/api/client';

type Notification = {id:string;title:string;body:string;href:string;created_at:string;read:boolean};

export default function NotificationCenter({compact=false}:{compact?:boolean}) {
  const [items,setItems]=useState<Notification[]>([]),[unread,setUnread]=useState(0);
  const load=useCallback(async()=>{const response=await fetch('/api/backend/api/v1/notifications?limit=30');if(!response.ok)return;const body=await response.json();setItems(body.items);setUnread(body.unread_count);},[]);
  useEffect(()=>{void load();},[load]);
  async function markRead(item:Notification){if(!item.read)await fetch(`/api/backend/api/v1/notifications/${item.id}/read`,{method:'POST'});await load();}
  async function markAll(){await fetch('/api/backend/api/v1/notifications/read-all',{method:'POST'});await load();}
  if(compact&&!items.length)return null;
  return <section className="notification-center" aria-label="Notifications"><header><div><Bell size={17}/><h2>Updates</h2>{unread>0&&<span>{unread} new</span>}</div>{unread>0&&<button type="button" onClick={markAll}><CheckCheck size={15}/>Mark all read</button>}</header>{items.length?<div className="notification-list">{items.map(item=><Link key={item.id} href={item.href} className={item.read?'read':''} onClick={()=>void markRead(item)}><span aria-hidden="true"/><div><strong>{item.title}</strong><p>{item.body}</p><small>{new Date(item.created_at).toLocaleString('en-UG')}</small></div></Link>)}</div>:<p className="notification-empty">No updates yet. Important support activity will appear here.</p>}</section>;
}
