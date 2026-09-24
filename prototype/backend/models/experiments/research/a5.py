from prep import *
import lightgbm as lgb, warnings; warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
s=load()
LEAN=BASE+['hour_sin','hour_cos','leader_log_ratio','line_irreg30','line_n30','leader_changed','close1','close3','close5','delay_change3','L_close3']
P=dict(objective='binary',learning_rate=0.05,num_leaves=31,min_child_samples=200,subsample=0.8,subsample_freq=1,colsample_bytree=0.8,reg_lambda=1.0,verbose=-1,n_estimators=600)
def lr(tr,te,cols,yk):
    X=tr[cols].fillna(0).values; mu,sd=X.mean(0),X.std(0); sd[sd==0]=1
    m=LogisticRegression(max_iter=3000).fit((X-mu)/sd,tr[yk]); return m.predict_proba((te[cols].fillna(0).values-mu)/sd)[:,1]
def gb(tr,te,cols,yk): return lgb.LGBMClassifier(**P).fit(tr[cols],tr[yk]).predict_proba(te[cols])[:,1]
print('== horizon k (fixed split Fri+Sun test)')
R={}
for k in (3,5,10):
    yk=f'y{k}'; ss=s[s[yk].notna()]; tr=ss[ss.day.isin(TRAIN)]; te=ss[ss.day.isin(TEST)]
    R[f'k={k} LR production']=ev(te[yk].values,lr(tr,te,BASE,yk))
    R[f'k={k} GBM lean']=ev(te[yk].values,gb(tr,te,LEAN,yk))
    R[f'k={k} gap rule']=ev(te[yk].values,-te.ratio.values)
print(pd.DataFrame(R).T.to_string())
print('\n== leave-one-day-out CV, k=10 (each day predicted by a model trained on the other 6)')
ss=s[s.y10.notna()]; rows=[]
for d in DAYS:
    tr=ss[ss.day!=d]; te=ss[ss.day==d]; y=te.y10.values
    rows.append(dict(day=d, base=round(y.mean(),4), LR_prod=round(average_precision_score(y,lr(tr,te,BASE,'y10')),3),
        LR_lean=round(average_precision_score(y,lr(tr,te,LEAN,'y10')),3),GBM_base=round(average_precision_score(y,gb(tr,te,BASE,'y10')),3),
        GBM_lean=round(average_precision_score(y,gb(tr,te,LEAN,'y10')),3)))
    print(rows[-1])
cv=pd.DataFrame(rows).set_index('day'); print(cv.to_string()); print('mean', cv.mean().round(3).to_dict())
print('GBM_lean beats LR_prod on', (cv.GBM_lean>cv.LR_prod).sum(),'/7 days; beats GBM_base on',(cv.GBM_lean>cv.GBM_base).sum(),'/7')
cv.to_csv('cv.csv')
