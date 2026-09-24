"""Historical congestion matching, independent of map rendering and replay time.

Waze contains jam reports, not continuous coverage. A missing match is unknown.
Distances use a local equirectangular projection centred on Lisbon. Geometry
orientation is not a reliable travel direction, so alignment is bidirectional.
"""

from collections import defaultdict
from math import ceil, cos, floor, hypot, isfinite, radians
import re

MATCH_METERS = 25
STEP_METERS = 25
CELL_METERS = 100
X_SCALE = 111_195 * cos(radians(38.73))
Y_SCALE = 111_195


def speed_ratio(intensity):
    """Midpoint of the source's percentage band; never infer from road speed."""
    value = intensity.strip().casefold()
    if value == 'estrada bloqueada':
        return 0.0
    match = re.fullmatch(r'(80|60|40|20)%\s+a\s+(61|41|21|1)%\s+da velocidade de fluxo livre', value)
    if not match:
        return None
    high, low = map(int, match.groups())
    return (high + low) / 2 if high - low == 19 else None


def parse_linestring(wkt):
    match = re.fullmatch(r'\s*LINESTRING\s*\(([^()]*)\)\s*', wkt, re.I)
    if not match:
        return []
    try:
        points = [tuple(map(float, pair.split())) for pair in match[1].split(',')]
    except ValueError:
        return []
    if len(points) < 2 or any(len(p) != 2 or not all(map(isfinite, p))
                              or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90)
                              for p in points):
        return []
    return [(lat, lon) for lon, lat in points]


def project(point):
    lat, lon = point
    return (lon + 9.15) * X_SCALE, (lat - 38.73) * Y_SCALE


def pieces(points):
    for a, b in zip(points, points[1:]):
        ax, ay = project(a)
        bx, by = project(b)
        distance = hypot(bx - ax, by - ay)
        if distance < 0.01:
            continue
        count = max(1, ceil(distance / STEP_METERS))
        for i in range(count):
            yield ([a[j] + (b[j] - a[j]) * i / count for j in (0, 1)],
                   [a[j] + (b[j] - a[j]) * (i + 1) / count for j in (0, 1)])


def distance_to_segment(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
    return hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


class TrafficIndex:
    def __init__(self, rows):
        self.grid = defaultdict(list)
        self.records = defaultdict(list)
        self.ignored_reports = 0
        for row in rows:
            ratio = speed_ratio(row['intensity'])
            points = parse_linestring(row['geometry_wkt'])
            if ratio is None or not points:
                self.ignored_reports += row['reports']
                continue
            key = row['geometry_wkt']
            if key not in self.records:
                for start, end in pieces(points):
                    a, b = project(start), project(end)
                    # Expand each short road segment's box by the match radius.
                    for x in range(floor((min(a[0], b[0]) - MATCH_METERS) / CELL_METERS),
                                   floor((max(a[0], b[0]) + MATCH_METERS) / CELL_METERS) + 1):
                        for y in range(floor((min(a[1], b[1]) - MATCH_METERS) / CELL_METERS),
                                       floor((max(a[1], b[1]) + MATCH_METERS) / CELL_METERS) + 1):
                            self.grid[x, y].append((key, a, b))
            self.records[key].append((row['operational_date'], ratio, row['reports'],
                                      row['speed_kmh'], row.get('speed_reports', row['reports'])))

    def matching_keys(self, start, end):
        a, b = project(start), project(end)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = hypot(dx, dy)
        matched = set()
        for key, c, d in self.grid.get((floor(mid[0] / CELL_METERS), floor(mid[1] / CELL_METERS)), []):
            if key in matched:
                continue
            ex, ey = d[0] - c[0], d[1] - c[1]
            # Reject crossing streets (>30 degrees), accept reversed WKT order.
            alignment = abs(dx * ex + dy * ey) / (length * hypot(ex, ey))
            if alignment >= cos(radians(30)) and distance_to_segment(mid, c, d) <= MATCH_METERS:
                matched.add(key)
        return matched

    def match(self, start, end):
        matched = self.matching_keys(start, end)
        days = defaultdict(lambda: [0.0, 0, 0.0, 0])
        for key in sorted(matched):
            for day, ratio, reports, speed, speed_reports in self.records[key]:
                value = days[day]
                value[0] += ratio * reports
                value[1] += reports
                if speed is not None and isfinite(speed) and speed >= 0:
                    value[2] += speed * speed_reports
                    value[3] += speed_reports
        if not days:
            return dict(speedRatio=None, speedKmh=None, reports=0, days=0)
        speeds = [v[2] / v[3] for v in days.values() if v[3]]
        return dict(speedRatio=round(sum(v[0] / v[1] for v in days.values()) / len(days), 1),
                    speedKmh=round(sum(speeds) / len(speeds), 1) if speeds else None,
                    reports=sum(v[1] for v in days.values()), days=len(days))

    def route(self, route):
        sections = []
        matched_length = total_length = 0.0
        for shape in route['shapes']:
            previous = None
            for start, end in pieces(shape['points']):
                length = hypot(*(b - a for a, b in zip(project(start), project(end))))
                # Stop-to-stop fallback lines are not road geometry.
                evidence = (dict(speedRatio=None, speedKmh=None, reports=0, days=0)
                            if shape['shape_id'].startswith('stops-') else self.match(start, end))
                total_length += length
                if evidence['days']:
                    matched_length += length
                if previous is not None and all(previous[k] == v for k, v in evidence.items()):
                    previous['points'].append(end)
                else:
                    previous = dict(shapeId=shape['shape_id'], directionId=shape['direction_id'],
                                    points=[start, end], **evidence)
                    sections.append(previous)
        return dict(key=route['key'], sections=sections,
                    matchedMeters=round(matched_length), totalMeters=round(total_length))
