import pandas as pd,numpy as np
from sklearn.metrics import roc_auc_score,average_precision_score,precision_recall_curve
DAYS=['2026-08-31','2026-09-01','2026-09-02','2026-09-03','2026-09-04','2026-09-05','2026-09-06']
TRAIN=['2026-08-31','2026-09-01','2026-09-02','2026-09-03','2026-09-05']; TEST=['2026-09-04','2026-09-06']
def load():
    d=pd.read_pickle('feat.pkl')
    s=d[(d.valid==1)&(d.bunched==0)&(d.ratio>=0.5)].copy()
    loc=s.t.dt.tz_convert('Europe/Lisbon'); h=loc.dt.hour+loc.dt.minute/60
    s['log_ratio']=np.log(s.ratio.clip(0.05,3)); tr=(s.ratio-s.ratio_prev).fillna(0).clip(-3,3); s['trend']=tr
    s['delay_min']=s.delay/60; s['lead_delay_min']=s.lead_delay/60; s['delay_gap_min']=(s.lead_delay-s.delay)/60
    s['prev_trip_delay_min']=s.prev_trip_delay.fillna(0)/60; s['sched_hw_min']=s.sched_hw/60
    s['peak_am']=((loc.dt.hour>=7)&(loc.dt.hour<=9)).astype(float); s['peak_pm']=((loc.dt.hour>=17)&(loc.dt.hour<=19)).astype(float)
    s['weekend']=(loc.dt.weekday>=5).astype(float); s['hour_sin']=np.sin(2*np.pi*h/24); s['hour_cos']=np.cos(2*np.pi*h/24)
    s['leader_log_ratio']=np.log(s.L_ratio.clip(0.05,3)); s['f_log_ratio']=np.log(s.f_ratio.clip(0.05,3))
    s['line_key']=s.line+'|'+s.direction_id; s['stop_key']=s.line_key+'|'+s.stop_id
    return s
BASE=['log_ratio','trend','delay_min','lead_delay_min','sched_hw_min','progress','peak_am','peak_pm','weekend','delay_gap_min','prev_trip_delay_min']
def te(s,key,y,train_days,smooth=200):
    out=pd.Series(np.nan,index=s.index); tr=s[s.day.isin(train_days)]; prior=tr[y].mean()
    def enc(src,dst):
        g=src.groupby(key)[y].agg(['sum','count']); r=(g['sum']+smooth*prior)/(g['count']+smooth); return dst[key].map(r).fillna(prior)
    for dd in train_days: out[s.day==dd]=enc(tr[tr.day!=dd],s[s.day==dd])
    rest=~s.day.isin(train_days); out[rest]=enc(tr,s[rest]); o=out.clip(1e-4,1-1e-4); return np.log(o/(1-o))
def ev(y,p):
    prec,rec,_=precision_recall_curve(y,p); top=p>=np.quantile(p,.99)
    return dict(base=round(y.mean(),4),auc=round(roc_auc_score(y,p),3),ap=round(average_precision_score(y,p),3),lift=round(average_precision_score(y,p)/y.mean(),1),
                p28=round(prec[rec>=.28].max(),3),prec100=round(y[top].mean(),3),rec100=round(y[top].sum()/y.sum(),3))
