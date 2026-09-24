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
