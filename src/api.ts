import {validate} from './replay';
export type Availability={datasetVersion:number;partialPreview?:boolean;importProgress?:{completedFiles:number;committedObservations:number};areas:{id:string;name:string}[];operators:{id:string;name:string}[];dates:string[]};
export type ScheduleRoute={agency_id:string;package_id:number;route_id:string;line_short_name:string;route_long_name:string;directions:string[];target:boolean;corridor:string;areas:string[]};
export type Selection={areas:string[];operators:string[];date:string;start:string;end:string;preview?:boolean;datasetVersion?:number;scheduleMode?:boolean;routeId?:string;directionId?:string};
export const defaults:Selection={areas:['eycs2'],operators:['IA9T6','LA77N','BNA17','YA15B','A2L1N'],date:'2026-09-01',start:'07:00',end:'09:00'};
export function queryFor(s:Selection){const p=new URLSearchParams({date:s.date,start:s.start,end:s.end});if(s.preview){p.set('preview','true');if(s.datasetVersion)p.set('dataset_version',String(s.datasetVersion));}if(s.scheduleMode){p.set('schedule_mode','true');if(s.routeId)p.set('route_id',s.routeId);if(s.directionId)p.set('direction_id',s.directionId);}s.areas.forEach(a=>p.append('area',a));s.operators.forEach(o=>p.append('operator',o));return p.toString();}
export async function jsonRequest(url:string,signal?:AbortSignal){const r=await fetch(url,{signal});if(!(r.headers.get('content-type')||'').includes('json'))throw Error('API unavailable. Start Docker Compose and import data; see README.');const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:`Request failed (${r.status}). Check the selection.`);return value;}
export class LatestRequest{
 private controller?:AbortController;private generation=0;
 cancel(){this.controller?.abort();this.generation++;}
 async run<T>(work:(signal:AbortSignal)=>Promise<T>):Promise<T|undefined>{this.cancel();const n=this.generation;this.controller=new AbortController();try{const result=await work(this.controller.signal);return n===this.generation?result:undefined;}catch(e){if(n!==this.generation)return undefined;throw e;}}
}
export const loadSelection=async(s:Selection,signal:AbortSignal)=>validate(await jsonRequest(`/api/observations?${queryFor(s)}`,signal));
