"""
Run everything in order and export files for the backend.

Owner:  A
Input:  config.yaml
Output: data/processed/*, data/serving/*

TODO
  [ ] load → detect → features → predict → simulate
  [ ] export serving files: network geojson, replay frames every 10 s, events, kpis, heatmap
  [ ] run with: python -m src.pipeline
"""
