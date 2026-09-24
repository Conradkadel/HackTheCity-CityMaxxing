"""
Build the ML dataset.

Owner:  B
Input:  stop_passages, headways, calendar, (waze)
Output: X, y, train/test split

TODO
  [ ] make_labels(): pair becomes bunched within next N stops; only rows not yet bunched; drop rows whose future is unobserved
  [ ] make_features(): headway ratio + trend over last stops, leader/follower delay, speeds, route position, hour, day_type, corridor headway, space gap
  [ ] split_by_day(): train Mon–Thu, test Fri–Sun (never random)
  [ ] SAME make_features used in training and prediction
"""
