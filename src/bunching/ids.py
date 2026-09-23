"""
Parse trip_id per agency → line_id, pattern_id, direction, sched start.

OWNER:   A
INPUT:   trip_id strings
OUTPUT:  parsed fields

TODO:
  [ ] CM Área 1/3 format: 1715_0_1_0600_0629_0_7
  [ ] CM Área 2/4 format: 2605_1_1|1|2|2040
  [ ] MobiCascais: M13-1-012-...
  [ ] Carris: unknown → line_id None until mapping arrives
"""
