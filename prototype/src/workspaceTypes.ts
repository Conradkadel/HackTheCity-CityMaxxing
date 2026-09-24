export type AreaOption = { id: string; name: string; observations: number };
export type OperatorOption = { id: string; name: string; observations: number };

export type CatalogRoute = {
  key: string;
  package_id: number;
  route_id: string;
  line_short_name: string;
  route_long_name: string;
  route_color: string;
  agency_name: string;
  agency_id: string;
  directions: string[];
  trip_count: number;
  corridors: string[];
  is_challenge: boolean;
};

export type ConfiguredLine = {
  code: string;
  mode: string;
  planAvailable: boolean;
  vehicleAvailable: boolean;
  routeKeys: string[];
};

export type WorkspacePreset = {
  id: string;
  name: string;
  color: string;
  operatorAgencyIds: string[];
  operators: { id: string; name: string; available: boolean }[];
  lines: ConfiguredLine[];
  zones: { id: string; name: string; geohashes: string[] }[];
  warnings: string[];
};

export type WorkspaceCatalog = {
  version: number;
  datasetVersion: number;
  date: string;
  dates: string[];
  defaultPresetId: string;
  areas: AreaOption[];
  operators: OperatorOption[];
  presets: WorkspacePreset[];
  routes: CatalogRoute[];
  referenceZones: {
    presetId: string;
    presetName: string;
    zoneId: string;
    name: string;
    geohashes: string[];
  }[];
  limits: { maxWindowHours: number; maxObservations: number };
};

export type VehicleMode = "configured" | "all";
export type VehicleFilters = {
  date: string;
  start: string;
  end: string;
  areas: string[];
  operators: string[];
  lines: string[];
  vehicleMode: VehicleMode;
};

export type RouteShape = {
  shape_id: string;
  direction_id: string;
  points: [number, number][];
};
export type RouteStop = {
  stop_id: string;
  stop_name: string;
  stop_sequence: number;
  direction_id: string;
  lat: number;
  lon: number;
};
export type RouteGeometry = CatalogRoute & {
  shapes: RouteShape[];
  stops: RouteStop[];
  bounds: [[number, number], [number, number]] | null;
};

export type VehicleDayLine = {
  line: string;
  mode: string;
  routes: string[];
  trips: string[];
  observations: number;
  firstReport: number;
  lastReport: number;
};

export type VehicleDayPeriod = {
  line: string | null;
  routeId: string | null;
  tripId: string | null;
  start: number;
  end: number;
  observations: number;
  startArea: string;
  endArea: string;
};

export type VehicleDayGap = {
  start: number;
  end: number;
  durationSeconds: number;
  fromArea: string;
  toArea: string;
  fromLine: string | null;
  toLine: string | null;
  areaChanged: boolean;
  lineChanged: boolean;
};

export type VehicleStopReport = {
  reportedTime: number;
  tripId: string;
  stopId: string;
  stopName: string | null;
  line: string;
  routeId: string;
  directionId: string;
  stopSequence: number;
  scheduledTime: number | null;
  differenceSeconds: number | null;
};

export type VehicleDay = {
  date: string;
  operatorId: string;
  operatorName: string;
  vehicleId: string;
  firstReport: number;
  lastReport: number;
  observations: number;
  unresolvedObservations: number;
  areas: string[];
  lines: VehicleDayLine[];
  linePeriods: VehicleDayPeriod[];
  gaps: VehicleDayGap[];
  stopReports: VehicleStopReport[];
  gapThresholdSeconds: number;
};

export type LineScheduledStop = {
  stopId: string;
  stopName: string;
  stopSequence: number;
  arrivalTime: string;
  departureTime: string;
  scheduledTime: number | null;
  reportedTime: number | null;
  differenceSeconds: number | null;
  reportObservations: number;
};

export type LineRun = {
  vehicleId: string;
  tripId: string;
  packageId: number;
  routeId: string;
  routeName: string;
  directionId: string;
  firstReport: number;
  lastReport: number;
  observations: number;
  scheduledStart: number | null;
  scheduledEnd: number | null;
  scheduledStops: LineScheduledStop[];
  reportedStops: number;
};

export type BunchingCandidate = {
  stopId: string;
  stopName: string;
  stopSequence: number;
  directionId: string;
  routeId: string;
  firstVehicleId: string;
  firstTripId: string;
  secondVehicleId: string;
  secondTripId: string;
  firstReportedTime: number;
  secondReportedTime: number;
  observedGapSeconds: number;
  plannedGapSeconds: number;
};

export type LineDay = {
  date: string;
  operatorId: string;
  operatorName: string;
  line: string;
  mode: string;
  runs: LineRun[];
  bunchingCandidates: BunchingCandidate[];
  thresholds: {
    maximumObservedGapSeconds: number;
    minimumPlannedGapSeconds: number;
  };
  coverage: {
    vehicles: number;
    runs: number;
    scheduledStops: number;
    reportedStops: number;
    unmatchedReportedStops: number;
  };
  warnings: string[];
  evidenceNote: string;
};

export type BunchingWeekEpisode = {
  id: number;
  routeId: string;
  directionId: string;
  vehicleAId: string;
  tripAId: string;
  vehicleBId: string;
  tripBId: string;
  startTimestamp: number;
  endTimestamp: number;
  firstStopId: string;
  firstStopName: string;
  lastStopId: string;
  lastStopName: string;
  evidenceCount: number;
  distinctStopCount: number;
  minimumObservedGapSeconds: number;
  maximumPlannedGapSeconds: number;
  latitude: number | null;
  longitude: number | null;
};

export type BunchingWeek = {
  datasetVersion: number;
  detectorVersion: string;
  operatorId: string;
  line: string;
  weekStart: string;
  weekEnd: string;
  analyzedDays: number;
  totalEpisodes: number;
  days: {
    date: string;
    analysisAvailable: boolean;
    analysisRunId: number | null;
    episodes: BunchingWeekEpisode[];
  }[];
  evidenceNote: string;
};

export type BunchingWeekSummary = {
  datasetVersion: number;
  detectorVersion: string;
  weekStart: string;
  weekEnd: string;
  lines: {
    operatorId: string;
    line: string;
    analyzedDays: number;
    candidateEpisodes: number;
    evidencePoints: number;
  }[];
  evidenceNote: string;
};
