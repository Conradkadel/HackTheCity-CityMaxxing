import pandas as pd, numpy as np, time
t0=time.time()
d=pd.read_pickle('raw.pkl')
d['tid']=d.trip_id+'|'+d.vehicle_id
d=d.sort_values(['day','tid','seq']).reset_index(drop=True)
g=d.groupby(['day','tid'],sort=False)
ts=d.t.astype('int64')//10**9; d['ts']=ts
# --- own history along the trip (all known at time t)
d['dwell']=(d.t-d.t_first).dt.total_seconds()
for k in (1,3,5):
    d[f'ratio_l{k}']=g.ratio.shift(k)
    d[f'hw_l{k}']=g.hw.shift(k)
    d[f'ts_l{k}']=g.ts.shift(k)
d['run1']=d.ts-d.ts_l1                       # own run time from previous stop
d['close1']=d.hw-d.hw_l1                     # gap change (s) over last stop (+ = opening)
d['close3']=(d.hw-d.hw_l3)/3
d['close5']=(d.hw-d.hw_l5)/5
d['leader_changed']=(d.leader_trip!=g.leader_trip.shift(1)).astype(float)
d.loc[g.cumcount()==0,'leader_changed']=np.nan
d['dwell_mean3']=g.dwell.transform(lambda s:s.rolling(3,min_periods=1).mean())
d['stops_left']=d.last_seq-d.seq
d['t_in_trip']=(d.ts-g.ts.transform('min'))/60
d['delay_change3']=(d.delay-g.delay.shift(3))/60
# --- leader state at this stop (leader passed earlier -> known)
L=d[['day','tid','stop_id','ratio','dwell','delay','stops_left','close3','run1','seq']].rename(columns=lambda c:'L_'+c if c not in('day',) else c)
d['ltid']=d.leader_trip+'|'+d.leader_vehicle
d=d.merge(L,left_on=['day','ltid','stop_id'],right_on=['day','L_tid','stop_id'.join(['L_',''])],how='left')
d['lead_run_diff']=d.run1-d.L_run1           # >0: I was slower than my leader on last segment
# --- follower (bus behind): its latest passage before t, where its leader is me
F=d.loc[d.ltid.notna(),['day','ltid','ts','ratio','hw']].rename(columns={'ltid':'tid','ts':'f_ts','ratio':'f_ratio','hw':'f_hw'}).sort_values('f_ts')
d=d.sort_values('ts')
d=pd.merge_asof(d,F,left_on='ts',right_on='f_ts',by=['day','tid'],direction='backward',allow_exact_matches=False)
d['f_age']=(d.ts-d.f_ts)/60
d.loc[d.f_age>30,['f_ratio','f_hw']]=np.nan
# --- line/direction irregularity in the last 30 min (other buses, before t)
d=d.sort_values(['day','line','direction_id','ts']).reset_index(drop=True)
d['absdev']=np.abs(np.log(d.ratio.clip(0.05,3)))
d['_t']=pd.to_datetime(d.ts,unit='s')
out=[]
for _,grp in d.groupby(['day','line','direction_id'],sort=False):
    r=grp.set_index('_t').absdev.rolling('30min',closed='left')
    out.append(pd.DataFrame({'line_irreg30':r.mean().values,'line_n30':r.count().values},index=grp.index))
d=d.join(pd.concat(out))
# --- labels at several horizons (own trip, next k stops bunched)
d=d.sort_values(['day','tid','seq']).reset_index(drop=True)
g=d.groupby(['day','tid'],sort=False)
for k in (3,5,10):
    fut=sum(g.bunched.shift(-i).fillna(0) for i in range(1,k+1))
    has=g.bunched.shift(-1).notna()
    d[f'y{k}']=np.where(has,(fut>0).astype(float),np.nan)
print('check y10 == label:',((d.y10==d.label)|(d.label.isna()&d.y10.isna())).mean())
d.drop(columns=['_t']).to_pickle('feat.pkl'); print('done',round(time.time()-t0),'s',d.shape)
