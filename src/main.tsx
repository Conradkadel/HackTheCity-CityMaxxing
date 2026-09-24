import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';
import {clock,colors,indexObservations,keyOf,snapshot,validate,type Dataset} from './replay';
import {demo} from './demo';
import {defaults,jsonRequest,LatestRequest,loadSelection,type Availability,type Selection} from './api';
import {Plans} from './Plans';
import {geohashBounds} from './geohash';

const dateLabel=(ts:number)=>new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Lisbon',dateStyle:'medium'}).format(ts);
const stamp=(ts:number)=>`${dateLabel(ts)} ${clock(ts)}`;
const toggle=(items:string[],id:string)=>items.includes(id)?items.filter(x=>x!==id):[...items,id];
function App(){
 const [data,setData]=useState<Dataset|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[time,setTime]=useState(0),[playing,setPlaying]=useState(false),[speed,setSpeed]=useState(30),[operators,setOperators]=useState(new Set<string>()),[selected,setSelected]=useState<string|null>(null),[tileError,setTileError]=useState(false);
 const [availability,setAvailability]=useState<Availability|null>(null),[draft,setDraft]=useState<Selection>(defaults),[apiReady,setApiReady]=useState(false),[source,setSource]=useState(''),[dirty,setDirty]=useState(false),[showAreas,setShowAreas]=useState(true);
 const requests=useRef(new LatestRequest());
 const [preview,setPreview]=useState(false);
 const mapNode=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),markers=useRef(new Map<string,L.CircleMarker>()),areaLayer=useRef<L.LayerGroup|null>(null);
 const adopt=(d:Dataset,label:string)=>{setData(d);setTime(d.metadata.startTimestamp);setOperators(new Set(Object.keys(d.metadata.operators)));setPlaying(false);setSelected(null);setError('');setSource(label);setDirty(false);};
 async function load(s:Selection){
  if(!s.areas.length||!s.operators.length){setError('Select at least one area and operator.');return;}
  setLoading(true);setError('');
  try{const d=await requests.current.run(signal=>loadSelection(s,signal));if(d){adopt(d,s.preview?'INCOMPLETE IMPORT PREVIEW':'PostgreSQL dataset');setLoading(false);}}
  catch(e){setError((e as Error).message);setLoading(false);}
 }
 async function refresh(partial=preview){
  setLoading(true);setError('');
  try{const a=await requests.current.run(signal=>jsonRequest(`/api/availability?preview=${partial}`,signal)) as Availability|undefined;if(!a)return;setAvailability(a);setApiReady(true);setLoading(false);
   const s={...defaults,preview:partial,datasetVersion:a.datasetVersion,areas:defaults.areas.filter(id=>a.areas.some(x=>x.id===id)),operators:defaults.operators.filter(id=>a.operators.some(x=>x.id===id))};setDraft(s);
   if(partial){setDirty(true);setDraft({...s,date:a.dates.includes(s.date)?s.date:(a.dates[0]??s.date)});return;}
   if(a.dates.includes(s.date)&&s.areas.length&&s.operators.length)await load(s);
   else {setDraft({...s,date:a.dates[0]??s.date});setError('Choose available areas, operators and a calendar date, then load.');}
  }catch(e){setApiReady(false);setLoading(false);setError((e as Error).message);}
 }
 useEffect(()=>{void refresh();return()=>requests.current.cancel();},[]);
 function edit(p:Partial<Selection>){requests.current.cancel();setLoading(false);setDraft(s=>({...s,...p}));setDirty(true);}
 async function fallback(){setLoading(true);try{const d=await requests.current.run(async signal=>validate(await jsonRequest('/data/replay.json',signal)));if(d){adopt(d,'Local JSON fallback');setLoading(false);}}catch(e){setError((e as Error).message);setLoading(false);}}
 const index=useMemo(()=>indexObservations(data?.observations??[]),[data]);
 const visible=useMemo(()=>snapshot(index,time,operators),[index,time,operators]);
 const chosen=visible.find(o=>keyOf(o)===selected);
 useEffect(()=>{if(!mapNode.current)return;const m=L.map(mapNode.current,{preferCanvas:true,zoomControl:false}).setView([38.735,-9.12],12);map.current=m;areaLayer.current=L.layerGroup().addTo(m);L.control.zoom({position:'bottomright'}).addTo(m);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:19}).on('tileerror',()=>setTileError(true)).addTo(m);return()=>{m.remove();map.current=null;markers.current.clear();areaLayer.current=null;};},[]);
 useEffect(()=>{const layer=areaLayer.current;if(!layer)return;layer.clearLayers();if(!showAreas||!availability)return;for(const area of availability.areas){try{const selected=draft.areas.includes(area.id),cell=L.rectangle(geohashBounds(area.id),{color:selected?'#d1ed86':'#31788a',weight:selected?3:1,fillColor:selected?'#d1ed86':'#31788a',fillOpacity:selected?.18:.05,interactive:true});cell.bindTooltip(`${area.id} · ${area.name}${selected?' · selected':''}<br/>Click to ${selected?'remove':'add'} this area`,{sticky:true,className:'area-tooltip'});cell.on('click',()=>{requests.current.cancel();setLoading(false);setDraft(current=>({...current,areas:toggle(current.areas,area.id)}));setDirty(true);});cell.addTo(layer);}catch{/* Invalid API identifiers must not prevent the map from rendering. */}}},[availability,draft.areas,showAreas]);
 useEffect(()=>{if(data?.observations.length&&map.current)map.current.fitBounds(L.latLngBounds(data.observations.map(o=>[o.latitude,o.longitude] as L.LatLngTuple)),{padding:[35,35],maxZoom:15});},[data]);
 useEffect(()=>{const m=map.current;if(!m)return;const keys=new Set(visible.map(keyOf));for(const [k,marker] of markers.current)if(!keys.has(k)){marker.remove();markers.current.delete(k);}for(const o of visible){const k=keyOf(o);let marker=markers.current.get(k);if(!marker){marker=L.circleMarker([o.latitude,o.longitude],{radius:7}).addTo(m).on('click',()=>setSelected(k));markers.current.set(k,marker);}const tip=document.createElement('span');tip.textContent=`${data?.metadata.operators[o.operatorId]} · ${o.vehicleId}`;marker.unbindTooltip().bindTooltip(tip);marker.setLatLng([o.latitude,o.longitude]);marker.setStyle({radius:k===selected?10:7,color:k===selected?'#ffffff':'#18354a',weight:2,fillColor:colors[o.operatorId]??'#889aaa',fillOpacity:o.stale?.3:.95,opacity:o.stale?.4:1});}},[visible,selected,data]);
 useEffect(()=>{if(!playing||!data)return;let last=performance.now();const handle=setInterval(()=>{const now=performance.now(),delta=(now-last)*speed;last=now;setTime(t=>Math.min(data.metadata.endTimestamp,t+delta));},100);return()=>clearInterval(handle);},[playing,speed,data]);
 useEffect(()=>{if(data&&time>=data.metadata.endTimestamp)setPlaying(false);},[time,data]);
 return <div className="app"><aside>
  <div className="brand"><span className="brandmark">h.</span> headway<span className="edition">PROJECT 07</span></div>
  <div className="intro"><div className="eyebrow">LISBON MOBILITY LAB</div><h1>Watch the city<br/>in motion.</h1><p>Explore recorded vehicle positions across selected geographic cells.</p></div>
  <div className="status"><span className="dot"/>{data?.metadata.synthetic?'SYNTHETIC DEMO':'HISTORICAL REPLAY'}</div>
  <h2>Data selection</h2>
  <label className="field"><span><input type="checkbox" checked={preview} onChange={e=>{const value=e.target.checked;setPreview(value);setAvailability(null);setDirty(true);void refresh(value);}}/> Preview incomplete import</span></label>
  {preview&&<div className="error" role="status">Partial coverage only. Completed files are visible; absence of vehicles is not evidence of no service. Refresh is manual and can take up to 30 seconds while the import is busy. Select areas and press Load selection.{availability?.importProgress&&<p>{availability.importProgress.completedFiles} files committed · {availability.importProgress.committedObservations.toLocaleString()} stored observations · dataset {availability.datasetVersion}</p>}</div>}
  <button onClick={()=>void refresh()} disabled={loading}>Refresh API availability</button>
  {availability&&<form onSubmit={e=>{e.preventDefault();void load(draft);}}>
   <label className="field">Lisbon calendar date<select aria-label="Lisbon calendar date" value={draft.date} onChange={e=>edit({date:e.target.value})}>{availability.dates.map(d=><option key={d}>{d}</option>)}</select></label>
   <div className="timefields"><label className="field">Start<input aria-label="Start time" type="time" required value={draft.start} onChange={e=>edit({start:e.target.value})}/></label><label className="field">End<input aria-label="End time" type="time" required value={draft.end} onChange={e=>edit({end:e.target.value})}/></label></div>
   <label className="field"><span><input type="checkbox" checked={showAreas} onChange={e=>setShowAreas(e.target.checked)}/> Show clickable area boundaries on map</span></label>
   <details><summary>Areas · {draft.areas.length} selected</summary><p className="muted area-help">The map shows available geohash cells. Click a boundary to add or remove it; selected cells are highlighted.</p><button type="button" className="secondary" disabled={!draft.areas.length} onClick={()=>{const bounds=L.latLngBounds(draft.areas.flatMap(geohashBounds));map.current?.fitBounds(bounds,{padding:[35,35],maxZoom:13});}}>Zoom to selected areas</button><div className="filters">{availability.areas.map(a=><label key={a.id}><input type="checkbox" checked={draft.areas.includes(a.id)} onChange={()=>edit({areas:toggle(draft.areas,a.id)})}/>{a.id} · {a.name}</label>)}</div></details>
   <details><summary>Query operators · {draft.operators.length} selected</summary><div className="filters">{availability.operators.map(o=><label key={o.id}><input type="checkbox" checked={draft.operators.includes(o.id)} onChange={()=>edit({operators:toggle(draft.operators,o.id)})}/>{o.name} ({o.id})</label>)}</div></details>
   <p className="muted">Europe/Lisbon calendar date, not TML operational date. Up to 4 hours / 200,000 reports including history. End before start means next day.</p>
   <button className="primary" disabled={loading}>Load selection</button>{dirty&&<p className="muted">Selection changed; the map still shows the last loaded data.</p>}
  </form>}
  {loading&&<p role="status">Loading… Previous replay remains available.</p>}
  {error&&<div className="error" role="alert">{error}</div>}
  {!apiReady&&<div className="fallback"><button onClick={()=>{requests.current.cancel();setLoading(false);adopt(demo,'Synthetic demo — not real data');}}>Explore synthetic demo</button><button onClick={()=>void fallback()}>Load local JSON fallback</button></div>}
  {data&&<><h2>Loaded data</h2><p className="area">{source}</p><p className="muted">{data.metadata.sourcePartition} · {stamp(data.metadata.startTimestamp)} → {stamp(data.metadata.endTimestamp)} · Europe/Lisbon</p>
   <h2>Visible operators (loaded data)</h2><div className="filters">{Object.entries(data.metadata.operators).map(([id,label])=><label key={id}><input type="checkbox" checked={operators.has(id)} onChange={()=>setOperators(old=>new Set(toggle([...old],id)))}/><span className="swatch" style={{background:colors[id]??'#889aaa'}}/><span>{label}</span></label>)}</div>
   <div className="stats"><div><strong>{visible.length}</strong><span>vehicles visible</span></div><div><strong>{visible.filter(o=>o.stale).length}</strong><span>stale reports</span></div></div>
   <h2>Vehicle inspector</h2>{chosen?<div className="inspector"><h3>Vehicle {chosen.vehicleId}</h3><dl>{[['Operator',`${data.metadata.operators[chosen.operatorId]} (${chosen.operatorId})`],['Trip',chosen.tripId||'Not supplied'],['Stop',chosen.stopId||'Not supplied'],['Geographic cell',chosen.geohash??data.metadata.sourcePartition],['Last report',stamp(chosen.timestamp)],['Report age',`${Math.floor(chosen.age)} seconds`],['Receipt time',stamp(chosen.receivedTimestamp)]].map(([k,v])=><React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>)}</dl></div>:<p className="muted">{selected?'Selected vehicle is hidden or its report has expired.':'Click a vehicle to inspect its latest report.'}</p>}</>}
  <div className="footnote">Strict area filtering: only reports in selected cells enter replay. A last in-area position can remain for 120s; exact boundary-crossing time is unknown.<br/><br/>Reports fade after 60s and expire after 120s. No interpolation. Event-time replay, not what a live system knew, a delay measure or a bunching detector. Carris records can include trams.</div>
 </aside><main><div className="map" ref={mapNode}/><div className="maplabel"><span className="dot"/>{source==='INCOMPLETE IMPORT PREVIEW'?'INCOMPLETE IMPORT PREVIEW':data?.metadata.synthetic?'SYNTHETIC DATA':'RECORDED POSITIONS'}<small>{data?`${dateLabel(time)} · EUROPE/LISBON`:'SELECT DATA TO BEGIN'}</small></div>
 {tileError&&<div className="tilewarning" role="status">Background tiles unavailable. Replay still works; check your internet connection.</div>}
 {data&&visible.length===0&&<div className="empty">{data.observations.length?'No recent vehicles at this time with the selected filters.':'No observations match this selection. Choose other areas, operators or times.'}</div>}
 <div className="legend"><span className="legendDot"/>Recent <span className="legendDot faded"/>60–120s old</div>
 {data&&<section className="timeline" aria-label="Replay controls"><div className="timelineTop"><div><div className="eyebrow">{dateLabel(time)}</div><div className="time">{clock(time)} <small>Europe/Lisbon</small></div></div><div className="playcontrols"><label>Speed <select aria-label="Replay speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}>{[1,10,30,60].map(x=><option key={x} value={x}>{x}×</option>)}</select></label><button className="primary" disabled={!data.observations.length} onClick={()=>{if(time>=data.metadata.endTimestamp)setTime(data.metadata.startTimestamp);setPlaying(!playing);}}>{playing?'Pause':'▶ Play'}</button></div></div><input aria-label="Replay time" className="slider" type="range" min={data.metadata.startTimestamp} max={data.metadata.endTimestamp} step={1000} value={time} onChange={e=>{setPlaying(false);setTime(Number(e.target.value));}}/><div className="rangeLabels"><span>{stamp(data.metadata.startTimestamp)}</span><span>Drag to explore</span><span>{stamp(data.metadata.endTimestamp)}</span></div></section>}
 </main></div>;
}
function Workspace(){const [mode,setMode]=useState('vehicles');return <><nav className="modebar" aria-label="Map mode"><button aria-pressed={mode==='vehicles'} onClick={()=>setMode('vehicles')}>Vehicle replay</button><button aria-pressed={mode==='plans'} onClick={()=>setMode('plans')}>Operation plans · 2025 reference</button></nav>{mode==='vehicles'?<App/>:<Plans/>}</>;}
createRoot(document.getElementById('root')!).render(<Workspace/>);
