from prep import *
s=load(); s=s[s.y10.notna()]; print(len(s), s.y10.mean())
NEW=['close1','close3','close5','leader_changed','dwell','dwell_mean3','L_dwell','run1','lead_run_diff','L_close3','stops_left','L_stops_left','t_in_trip','delay_change3','leader_log_ratio','f_log_ratio','f_age','line_irreg30','line_n30','hour_sin','hour_cos']
print('univariate AUC / rate by quantile bins')
for c in NEW:
    v=s[c]; m=v.notna()
    a=roc_auc_score(s.y10[m],v[m]); 
    try: q=s[m].groupby(pd.qcut(v[m],5,duplicates='drop'),observed=True).y10.mean().round(4).tolist()
    except Exception as e: q=str(e)
    print(f'{c:16} cover {m.mean():.2f} AUC {a:.3f} quintile rates {q}')
print('\nleader_changed:',s.groupby('leader_changed').y10.agg(['mean','size']).round(4).to_dict())
print('trend>0.5 & leader_changed share:', s[s.trend>0.5].leader_changed.mean().round(3), ' vs overall', s.leader_changed.mean().round(3))
