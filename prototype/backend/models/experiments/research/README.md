# Model research scripts (run offline on passages_line.csv.gz)
1. fe.py   – builds causal features + labels at horizons 3/5/10 from the export -> feat.pkl
2. prep.py – shared loading, base features, target encoding, metrics
3. a3.py   – univariate analysis of new features
4. a4.py   – feature-group ablation (LightGBM)
5. a5.py   – horizon comparison + leave-one-day-out CV
