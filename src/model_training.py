"""
Train and apply models.

Owner:  B
Input:  train/test sets
Output: data/models/model_<version>.pkl, predictions

TODO
  [ ] baseline_rule(): alert if headway_ratio < 0.5
  [ ] train_logreg(), train_lightgbm() with class weights
  [ ] calibrate probabilities
  [ ] save_model / load_model
  [ ] predict(snapshot): probability per bus pair + recommended action (hold follower X s)
"""
