from prep import *
import lightgbm as lgb, warnings; warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
s=load(); s=s[s.y10.notna()]
s['stop_te']=te(s,'stop_key','y10',TRAIN); s['line_te']=te(s,'line_key','y10',TRAIN)
tr=s[s.day.isin(TRAIN)]; ts=s[s.day.isin(TEST)]; y=ts.y10.values
P=dict(objective='binary',learning_rate=0.05,num_leaves=31,min_child_samples=200,subsample=0.8,subsample_freq=1,colsample_bytree=0.8,reg_lambda=1.0,verbose=-1,n_estimators=600)
def gbm(cols):
    m=lgb.LGBMClassifier(**P).fit(tr[cols],tr.y10); return m,m.predict_proba(ts[cols])[:,1]
G1=['hour_sin','hour_cos','leader_log_ratio']
DYN=['line_irreg30','line_n30']
HIST=['leader_changed','close1','close3','close5','delay_change3','L_close3']
POS=['stops_left','L_stops_left','t_in_trip']
FOL=['f_log_ratio']
DW=['dwell','dwell_mean3','L_dwell']
TE=['stop_te','line_te']
R={}
sets=[('base',BASE),('+time+leader',BASE+G1),('+line state now',BASE+G1+DYN),('+history/overtake',BASE+G1+DYN+HIST),
      ('+position',BASE+G1+DYN+HIST+POS),('+follower',BASE+G1+DYN+HIST+POS+FOL),('+dwell',BASE+G1+DYN+HIST+POS+FOL+DW),('+stop/line TE (all)',BASE+G1+DYN+HIST+POS+FOL+DW+TE)]
for n,c in sets:
    m,p=gbm(c); R['GBM '+n]=ev(y,p); print(n,R['GBM '+n])
imp=pd.Series(m.booster_.feature_importance('gain'),index=c); print((imp/imp.sum()).sort_values(ascending=False).round(3).head(20).to_string())
pd.DataFrame(R).T.to_csv('a4.csv'); print(pd.DataFrame(R).T.to_string())
