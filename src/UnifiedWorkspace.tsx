import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import {
  jsonRequest,
  LatestRequest,
  loadSelection,
  loadWorkspaceCatalog,
} from "./api";
import { geohashBounds } from "./geohash";
import {
  clock,
  colors,
  indexObservations,
  keyOf,
  snapshot,
  type Dataset,
  type Observation,
} from "./replay";
import { defaultFilters, filtersEqual, toggleValue } from "./workspaceState";
import type {
  CatalogRoute,
  RouteGeometry,
  VehicleFilters,
  WorkspaceCatalog,
  WorkspacePreset,
} from "./workspaceTypes";

type Tab = "routes" | "vehicles" | "details";
const DEFAULT_DATE = "2026-09-01";
const palette = [
  "#10b981",
  "#3b82f6",
  "#f97316",
  "#a855f7",
  "#ec4899",
  "#06b6d4",
  "#eab308",
];

const formatDate = (timestamp: number) =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Lisbon",
    dateStyle: "medium",
  }).format(timestamp);
const formatStamp = (timestamp: number) =>
  `${formatDate(timestamp)} ${clock(timestamp)}`;
const routeColor = (route: CatalogRoute | RouteGeometry, index = 0) => {
  const value = route.route_color;
  if (value && value !== "#277a91")
    return value.startsWith("#") ? value : `#${value}`;
  return palette[index % palette.length];
};

export function UnifiedWorkspace() {
  const [tab, setTab] = useState<Tab>("vehicles");
  const [catalog, setCatalog] = useState<WorkspaceCatalog | null>(null);
  const [draft, setDraft] = useState<VehicleFilters>({
    date: DEFAULT_DATE,
    start: "07:00",
    end: "09:00",
    areas: [],
    operators: [],
    lines: [],
    vehicleMode: "configured",
  });
  const [applied, setApplied] = useState<VehicleFilters | null>(null);
  const [data, setData] = useState<Dataset | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [loadingVehicles, setLoadingVehicles] = useState(false);
  const [error, setError] = useState("");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(30);
  const [selectedVehicleKey, setSelectedVehicleKey] = useState<string | null>(
    null,
  );
  const [lastSelectedVehicle, setLastSelectedVehicle] = useState<
    (Observation & { age: number; stale: boolean }) | null
  >(null);
  const [selectedRouteKeys, setSelectedRouteKeys] = useState<string[]>([]);
  const [routeGeometry, setRouteGeometry] = useState<RouteGeometry[]>([]);
  const [routeSearch, setRouteSearch] = useState("");
  const [showStops, setShowStops] = useState(false);
  const [showReferenceZones, setShowReferenceZones] = useState(false);
  const [areaControlOpen, setAreaControlOpen] = useState(false);
  const [tileError, setTileError] = useState(false);

  const mapNode = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const areaLayer = useRef<L.LayerGroup | null>(null);
  const referenceLayer = useRef<L.LayerGroup | null>(null);
  const routeLayer = useRef<L.LayerGroup | null>(null);
  const stopLayer = useRef<L.LayerGroup | null>(null);
  const markers = useRef(new Map<string, L.CircleMarker>());
  const catalogRequest = useRef(new LatestRequest());
  const vehicleRequest = useRef(new LatestRequest());
  const geometryRequest = useRef(new LatestRequest());
  const firstCatalog = useRef(true);

  const observationIndex = useMemo(
    () => indexObservations(data?.observations ?? []),
    [data],
  );
  const visible = useMemo(
    () =>
      snapshot(
        observationIndex,
        time,
        new Set(Object.keys(data?.metadata.operators ?? {})),
      ),
    [observationIndex, time, data],
  );
  const visibleSelected = visible.find(
    (item) => keyOf(item) === selectedVehicleKey,
  );
  const inspectedVehicle = visibleSelected ?? lastSelectedVehicle;
  const filtersDirty = !filtersEqual(applied, draft);
  const filterSelectionInvalid =
    !draft.areas.length ||
    !draft.operators.length ||
    (draft.vehicleMode === "configured" && !draft.lines.length);

  async function applyFilters(next = draft) {
    if (!next.areas.length || !next.operators.length) return;
    setLoadingVehicles(true);
    setError("");
    try {
      const result = await vehicleRequest.current.run((signal) =>
        loadSelection(next, signal),
      );
      if (!result) return;
      setData(result);
      setApplied({
        ...next,
        areas: [...next.areas],
        operators: [...next.operators],
        lines: [...next.lines],
      });
      setTime(result.metadata.startTimestamp);
      setPlaying(false);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoadingVehicles(false);
    }
  }

  useEffect(() => {
    const request = catalogRequest.current;
    setLoadingCatalog(true);
    setError("");
    void request
      .run((signal) => loadWorkspaceCatalog(draft.date, signal))
      .then((result) => {
        if (!result) return;
        const next = defaultFilters(result, draft.start, draft.end);
        setCatalog(result);
        setDraft(next);
        setSelectedRouteKeys([]);
        setRouteGeometry([]);
        if (firstCatalog.current) {
          firstCatalog.current = false;
          void applyFilters(next);
        } else {
          setData(null);
          setApplied(null);
        }
      })
      .catch((reason) => setError((reason as Error).message))
      .finally(() => setLoadingCatalog(false));
    return () => request.cancel();
    // The catalog intentionally reloads only when the selected date changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.date]);

  useEffect(() => {
    const request = geometryRequest.current;
    if (!selectedRouteKeys.length) {
      setRouteGeometry([]);
      return;
    }
    void request
      .run((signal) =>
        jsonRequest<RouteGeometry[]>("/api/plans/routes-geometry", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ route_keys: selectedRouteKeys }),
          signal,
        }),
      )
      .then((result) => {
        if (result) setRouteGeometry(result);
      })
      .catch((reason) => setError((reason as Error).message));
    return () => request.cancel();
  }, [selectedRouteKeys]);

  useEffect(() => {
    if (!mapNode.current) return;
    const instance = L.map(mapNode.current, {
      preferCanvas: true,
      zoomControl: false,
    }).setView([38.735, -9.12], 11);
    map.current = instance;
    areaLayer.current = L.layerGroup().addTo(instance);
    referenceLayer.current = L.layerGroup().addTo(instance);
    routeLayer.current = L.layerGroup().addTo(instance);
    stopLayer.current = L.layerGroup().addTo(instance);
    L.control.zoom({ position: "bottomright" }).addTo(instance);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    })
      .on("tileerror", () => setTileError(true))
      .addTo(instance);
    const markerStore = markers.current;
    return () => {
      instance.remove();
      map.current = null;
      markerStore.clear();
    };
  }, []);

  useEffect(() => {
    const layer = areaLayer.current;
    if (!layer || !catalog) return;
    layer.clearLayers();
    catalog.areas.forEach((area) => {
      const pending = draft.areas.includes(area.id);
      const active = applied?.areas.includes(area.id) ?? false;
      const changed = pending !== active;
      const rectangle = L.rectangle(geohashBounds(area.id), {
        color: changed ? "#f59e0b" : active ? "#277a91" : "#71868c",
        weight: changed ? 3 : active ? 2 : 1,
        dashArray: pending ? undefined : "5 5",
        fillColor: pending ? "#d1ed86" : "#91a1a5",
        fillOpacity: pending ? 0.12 : 0.025,
      });
      rectangle.bindTooltip(
        `${area.id} · ${area.name}<br>${pending ? "Enabled" : "Disabled"}${changed ? " · pending Apply" : ""}`,
      );
      rectangle.on("click", () =>
        setDraft((current) => ({
          ...current,
          areas: toggleValue(current.areas, area.id),
        })),
      );
      rectangle.addTo(layer);
    });
  }, [catalog, draft.areas, applied?.areas]);

  useEffect(() => {
    const layer = referenceLayer.current;
    if (!layer || !catalog) return;
    layer.clearLayers();
    if (!showReferenceZones) return;
    catalog.referenceZones
      .flatMap((zone) => zone.geohashes.map((hash) => ({ ...zone, hash })))
      .forEach((zone) => {
        const rectangle = L.rectangle(geohashBounds(zone.hash), {
          color: "#a855f7",
          weight: 1,
          dashArray: "3 4",
          fillOpacity: 0,
        });
        rectangle.bindTooltip(
          `${zone.presetName} · ${zone.name} · ${zone.hash}`,
        );
        rectangle.addTo(layer);
      });
  }, [catalog, showReferenceZones]);

  useEffect(() => {
    routeLayer.current?.clearLayers();
    stopLayer.current?.clearLayers();
    routeGeometry.forEach((route, routeIndex) => {
      const color = routeColor(route, routeIndex);
      route.shapes.forEach((shape) =>
        L.polyline(shape.points, { color, weight: 4, opacity: 0.78 })
          .bindTooltip(`${route.line_short_name} · ${route.route_long_name}`)
          .addTo(routeLayer.current!),
      );
      if (showStops)
        route.stops.forEach((stop) =>
          L.circleMarker([stop.lat, stop.lon], {
            radius: 4,
            color: "#173c48",
            weight: 1,
            fillColor: color,
            fillOpacity: 0.9,
          })
            .bindTooltip(`${stop.stop_name} · ${route.line_short_name}`)
            .addTo(stopLayer.current!),
        );
    });
  }, [routeGeometry, showStops]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const currentKeys = new Set(visible.map(keyOf));
    markers.current.forEach((marker, key) => {
      if (!currentKeys.has(key)) {
        marker.remove();
        markers.current.delete(key);
      }
    });
    visible.forEach((vehicle) => {
      const key = keyOf(vehicle);
      let marker = markers.current.get(key);
      if (!marker) {
        marker = L.circleMarker([vehicle.latitude, vehicle.longitude]).addTo(
          instance,
        );
        markers.current.set(key, marker);
      }
      marker.off("click").on("click", () => {
        setSelectedVehicleKey(key);
        setLastSelectedVehicle(vehicle);
        setTab("details");
      });
      marker.setLatLng([vehicle.latitude, vehicle.longitude]);
      marker.setRadius(
        key === selectedVehicleKey ? 10 : vehicle.isFocus ? 7 : 5,
      );
      marker.setStyle({
        color: key === selectedVehicleKey ? "#fff" : "#173c48",
        weight: 2,
        fillColor: colors[vehicle.operatorId] ?? "#788f98",
        fillOpacity: vehicle.stale ? 0.3 : vehicle.isFocus ? 0.95 : 0.5,
      });
      marker
        .unbindTooltip()
        .bindTooltip(
          `${data?.metadata.operators[vehicle.operatorId]} · ${vehicle.vehicleId}${vehicle.route?.line ? ` · ${vehicle.route.line}` : ""}`,
        );
    });
  }, [visible, selectedVehicleKey, data]);

  useEffect(() => {
    if (!playing || !data) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      setTime((value) =>
        Math.min(data.metadata.endTimestamp, value + (now - previous) * speed),
      );
      previous = now;
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, speed, data]);

  useEffect(() => {
    if (data && time >= data.metadata.endTimestamp) setPlaying(false);
  }, [time, data]);

  const filteredRoutes = useMemo(() => {
    const query = routeSearch.trim().toLowerCase();
    if (!catalog) return [];
    return catalog.routes.filter(
      (route) =>
        !query ||
        [
          route.line_short_name,
          route.route_long_name,
          route.route_id,
          route.agency_name,
        ].some((value) => value.toLowerCase().includes(query)),
    );
  }, [catalog, routeSearch]);

  const toggleRouteKeys = (keys: string[]) => {
    const allSelected =
      keys.length > 0 && keys.every((key) => selectedRouteKeys.includes(key));
    setSelectedRouteKeys((current) =>
      allSelected
        ? current.filter((key) => !keys.includes(key))
        : [...new Set([...current, ...keys])],
    );
  };

  return (
    <div className="workspace">
      <aside className="sidebar">
        <header className="workspace-header">
          <div className="brand">
            <span className="brandmark">h.</span> headway{" "}
            <span className="edition">PROJECT 07</span>
          </div>
          <p>Challenge 7 analysis workspace</p>
          <div className="window-grid">
            <label>
              Date
              <select
                value={draft.date}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    date: event.target.value,
                  }))
                }
              >
                {(catalog?.dates ?? [draft.date]).map((date) => (
                  <option key={date}>{date}</option>
                ))}
              </select>
            </label>
            <label>
              Start
              <input
                type="time"
                value={draft.start}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    start: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              End
              <input
                type="time"
                value={draft.end}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    end: event.target.value,
                  }))
                }
              />
            </label>
          </div>
        </header>
        <nav className="sidebar-tabs" aria-label="Workspace panels">
          {(["routes", "vehicles", "details"] as Tab[]).map((value) => (
            <button
              key={value}
              className={tab === value ? "active" : ""}
              onClick={() => setTab(value)}
            >
              {value[0].toUpperCase() + value.slice(1)}
              {value === "details" && selectedVehicleKey ? " •" : ""}
            </button>
          ))}
        </nav>
        <div className="sidebar-content">
          {tab === "routes" && (
            <RoutesPanel
              catalog={catalog}
              selectedKeys={selectedRouteKeys}
              search={routeSearch}
              filteredRoutes={filteredRoutes}
              showStops={showStops}
              showZones={showReferenceZones}
              onSearch={setRouteSearch}
              onToggleKeys={toggleRouteKeys}
              onClear={() => setSelectedRouteKeys([])}
              onShowStops={setShowStops}
              onShowZones={setShowReferenceZones}
            />
          )}
          {tab === "vehicles" && (
            <VehiclesPanel
              catalog={catalog}
              draft={draft}
              dirty={filtersDirty}
              loading={loadingVehicles || loadingCatalog}
              data={data}
              error={error}
              onDraft={setDraft}
              onApply={() => void applyFilters()}
            />
          )}
          {tab === "details" && (
            <DetailsPanel
              vehicle={inspectedVehicle}
              visible={!!visibleSelected}
              data={data}
            />
          )}
        </div>
      </aside>
      <main className="map-shell">
        <div className="map" ref={mapNode} />
        <div className="map-status">
          {data
            ? `${visible.length} vehicles visible`
            : "Apply vehicle filters to begin"}
          <small>{selectedRouteKeys.length} planned route variants shown</small>
        </div>
        <div className="area-control">
          <button
            className="area-control-toggle"
            onClick={() => setAreaControlOpen((value) => !value)}
          >
            Areas · {draft.areas.length}/{catalog?.areas.length ?? 0}
            {filtersDirty ? " •" : ""}
          </button>
          {areaControlOpen && (
            <div className="area-control-panel">
              <div className="area-actions">
                <button
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      areas: catalog?.areas.map((area) => area.id) ?? [],
                    }))
                  }
                >
                  Select all
                </button>
                <button
                  onClick={() =>
                    setDraft((current) => ({ ...current, areas: [] }))
                  }
                >
                  Clear
                </button>
              </div>
              <p>
                Boundaries remain visible. Orange means the change is waiting
                for Apply.
              </p>
              <p
                className={`map-filter-state ${filterSelectionInvalid ? "invalid" : filtersDirty ? "pending" : "applied"}`}
              >
                {filterSelectionInvalid
                  ? "Select at least one area and carrier; configured mode also needs one available line."
                  : filtersDirty
                    ? "Pending changes — loaded vehicles still use the last applied filters."
                    : "Area, carrier, and vehicle-line filters are applied."}
              </p>
              <div className="area-options">
                {catalog?.areas.map((area) => (
                  <label key={area.id}>
                    <input
                      type="checkbox"
                      checked={draft.areas.includes(area.id)}
                      onChange={() =>
                        setDraft((current) => ({
                          ...current,
                          areas: toggleValue(current.areas, area.id),
                        }))
                      }
                    />
                    <span>
                      <strong>{area.id}</strong>
                      {area.name}
                    </span>
                  </label>
                ))}
              </div>
              <button
                className="primary apply-map"
                disabled={filterSelectionInvalid || loadingVehicles}
                onClick={() => void applyFilters()}
              >
                Apply filters
              </button>
            </div>
          )}
        </div>
        {tileError && (
          <div className="tilewarning">
            Background tiles are unavailable; data layers still work.
          </div>
        )}
        {data && (
          <section className="timeline" aria-label="Replay controls">
            <div className="timelineTop">
              <div>
                <div className="eyebrow">{formatDate(time)}</div>
                <div className="time">
                  {clock(time)} <small>Europe/Lisbon</small>
                </div>
              </div>
              <div className="playcontrols">
                <label>
                  Speed
                  <select
                    value={speed}
                    onChange={(event) => setSpeed(Number(event.target.value))}
                  >
                    {[1, 10, 30, 60].map((value) => (
                      <option key={value} value={value}>
                        {value}×
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="primary"
                  onClick={() => {
                    if (time >= data.metadata.endTimestamp)
                      setTime(data.metadata.startTimestamp);
                    setPlaying((value) => !value);
                  }}
                >
                  {playing ? "Pause" : "▶ Play"}
                </button>
              </div>
            </div>
            <input
              className="slider"
              type="range"
              min={data.metadata.startTimestamp}
              max={data.metadata.endTimestamp}
              step={1000}
              value={time}
              onChange={(event) => {
                setPlaying(false);
                setTime(Number(event.target.value));
              }}
            />
            <div className="rangeLabels">
              <span>{formatStamp(data.metadata.startTimestamp)}</span>
              <span>Drag to explore</span>
              <span>{formatStamp(data.metadata.endTimestamp)}</span>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

type RoutesPanelProps = {
  catalog: WorkspaceCatalog | null;
  selectedKeys: string[];
  search: string;
  filteredRoutes: CatalogRoute[];
  showStops: boolean;
  showZones: boolean;
  onSearch(value: string): void;
  onToggleKeys(keys: string[]): void;
  onClear(): void;
  onShowStops(value: boolean): void;
  onShowZones(value: boolean): void;
};
function RoutesPanel({
  catalog,
  selectedKeys,
  search,
  filteredRoutes,
  showStops,
  showZones,
  onSearch,
  onToggleKeys,
  onClear,
  onShowStops,
  onShowZones,
}: RoutesPanelProps) {
  if (!catalog) return <p className="muted">Loading date-valid routes…</p>;
  const routesByOperator = filteredRoutes.reduce<
    { id: string; name: string; routes: CatalogRoute[] }[]
  >((groups, route) => {
    const existing = groups.find((group) => group.id === route.agency_id);
    if (existing) existing.routes.push(route);
    else
      groups.push({
        id: route.agency_id,
        name: route.agency_name,
        routes: [route],
      });
    return groups;
  }, []);
  return (
    <>
      <div className="panel-heading">
        <div>
          <span className="eyebrow">PLANNED NETWORK</span>
          <h1>Routes</h1>
        </div>
        <button disabled={!selectedKeys.length} onClick={onClear}>
          Clear
        </button>
      </div>
      <p className="muted">
        Route overlays are independent from vehicle filters. No routes are drawn
        until selected.
      </p>
      <h2>Configured groups</h2>
      <div className="preset-list">
        {catalog.presets.map((preset, presetIndex) => (
          <PresetRoutes
            key={preset.id}
            preset={preset}
            important={preset.id === catalog.defaultPresetId}
            open={presetIndex === 0}
            selectedKeys={selectedKeys}
            onToggleKeys={onToggleKeys}
          />
        ))}
      </div>
      <h2>Complete date-valid catalog</h2>
      <input
        className="search-input"
        type="search"
        placeholder="Search line, route or operator"
        value={search}
        onChange={(event) => onSearch(event.target.value)}
      />
      <div className="route-picker">
        {routesByOperator.map((group) => (
          <section className="route-operator-group" key={group.id}>
            <h3>
              {group.name} <small>{group.id}</small>
            </h3>
            {group.routes.map((route, index) => (
              <label
                className={`route-picker-item ${selectedKeys.includes(route.key) ? "selected" : ""}`}
                key={route.key}
              >
                <input
                  type="checkbox"
                  checked={selectedKeys.includes(route.key)}
                  onChange={() => onToggleKeys([route.key])}
                />
                <span
                  className="line-tag"
                  style={{ background: routeColor(route, index) }}
                >
                  {route.line_short_name}
                </span>
                <span className="route-info">
                  <strong>{route.route_long_name}</strong>
                  <small>{route.route_id}</small>
                </span>
              </label>
            ))}
          </section>
        ))}
        {!filteredRoutes.length && (
          <p className="empty-list">
            No routes are available for this date and search.
          </p>
        )}
      </div>
      <h2>Route display</h2>
      <label className="check-row">
        <input
          type="checkbox"
          checked={showStops}
          onChange={(event) => onShowStops(event.target.checked)}
        />{" "}
        Show representative stops
      </label>
      <label className="check-row">
        <input
          type="checkbox"
          checked={showZones}
          onChange={(event) => onShowZones(event.target.checked)}
        />{" "}
        Show configured six-character zones
      </label>
      <p className="selection-summary">
        {selectedKeys.length} route variants selected
      </p>
    </>
  );
}

function PresetRoutes({
  preset,
  important,
  open,
  selectedKeys,
  onToggleKeys,
}: {
  preset: WorkspacePreset;
  important: boolean;
  open: boolean;
  selectedKeys: string[];
  onToggleKeys(keys: string[]): void;
}) {
  const availableKeys = preset.lines.flatMap((line) => line.routeKeys);
  const selected =
    availableKeys.length > 0 &&
    availableKeys.every((key) => selectedKeys.includes(key));
  return (
    <details
      open={open}
      className={`preset-card ${important ? "important" : ""}`}
    >
      <summary>
        <span className="preset-dot" style={{ background: preset.color }} />
        <strong>{preset.name}</strong>
        {important && <span className="badge">Important</span>}
      </summary>
      <button
        className="group-toggle"
        disabled={!availableKeys.length}
        onClick={() => onToggleKeys(availableKeys)}
      >
        {selected ? "Remove group" : "Show group"}
      </button>
      <div className="configured-lines">
        {preset.lines.map((line) => {
          const checked =
            line.routeKeys.length > 0 &&
            line.routeKeys.every((key) => selectedKeys.includes(key));
          return (
            <label
              key={line.code}
              className={!line.planAvailable ? "unavailable" : ""}
            >
              <input
                type="checkbox"
                disabled={!line.planAvailable}
                checked={checked}
                onChange={() => onToggleKeys(line.routeKeys)}
              />
              <span>
                {line.code}
                {line.mode === "tram" ? " · tram" : ""}
              </span>
              {!line.planAvailable && <small>Unavailable</small>}
              <em>{line.routeKeys.length || ""}</em>
            </label>
          );
        })}
      </div>
      {preset.warnings.map((warning) => (
        <p className="coverage-warning" key={warning}>
          {warning}
        </p>
      ))}
    </details>
  );
}

type VehiclesPanelProps = {
  catalog: WorkspaceCatalog | null;
  draft: VehicleFilters;
  dirty: boolean;
  loading: boolean;
  data: Dataset | null;
  error: string;
  onDraft(value: React.SetStateAction<VehicleFilters>): void;
  onApply(): void;
};
function VehiclesPanel({
  catalog,
  draft,
  dirty,
  loading,
  data,
  error,
  onDraft,
  onApply,
}: VehiclesPanelProps) {
  if (!catalog) return <p className="muted">Loading vehicle coverage…</p>;
  const configuredOperators = catalog.presets.flatMap((preset) =>
    preset.operators.map((operator) => ({
      ...operator,
      presetName: preset.name,
    })),
  );
  const missingConfiguredOperators = configuredOperators.filter(
    (configured, index) =>
      !configured.available &&
      configuredOperators.findIndex((item) => item.id === configured.id) ===
        index,
  );
  const invalid =
    !draft.areas.length ||
    !draft.operators.length ||
    (draft.vehicleMode === "configured" && !draft.lines.length);
  return (
    <>
      <span className="eyebrow">RECORDED MOVEMENT</span>
      <h1>Vehicles</h1>
      <div className="segmented">
        <button
          className={draft.vehicleMode === "configured" ? "active" : ""}
          onClick={() =>
            onDraft((current) => ({ ...current, vehicleMode: "configured" }))
          }
        >
          Configured lines
        </button>
        <button
          className={draft.vehicleMode === "all" ? "active" : ""}
          onClick={() =>
            onDraft((current) => ({ ...current, vehicleMode: "all" }))
          }
        >
          All vehicles
        </button>
      </div>
      <h2>Carriers available on {catalog.date}</h2>
      <div className="filter-list">
        {catalog.operators.map((operator) => (
          <label key={operator.id}>
            <input
              type="checkbox"
              checked={draft.operators.includes(operator.id)}
              onChange={() =>
                onDraft((current) => ({
                  ...current,
                  operators: toggleValue(current.operators, operator.id),
                }))
              }
            />
            <span>
              <strong>{operator.name}</strong>
              <small>
                {operator.id} · {operator.observations.toLocaleString()}{" "}
                observations
              </small>
            </span>
          </label>
        ))}
        {missingConfiguredOperators.map((operator) => (
          <label className="unavailable" key={operator.id}>
            <input type="checkbox" disabled />
            <span>
              <strong>{operator.name}</strong>
              <small>
                {operator.id} · configured by {operator.presetName}
              </small>
              <small>Unavailable in vehicle data for this date</small>
            </span>
          </label>
        ))}
      </div>
      {draft.vehicleMode === "configured" ? (
        <>
          <h2>Configured vehicle lines</h2>
          <p className="muted">
            Unavailable entries stay visible so reduced databases are explicit.
          </p>
          {catalog.presets.map((preset, index) => (
            <details
              key={preset.id}
              open={index === 0}
              className="vehicle-preset"
            >
              <summary>
                <span
                  className="preset-dot"
                  style={{ background: preset.color }}
                />
                {preset.name}
              </summary>
              <div className="configured-lines">
                {preset.lines.map((line) => (
                  <label
                    key={line.code}
                    className={!line.vehicleAvailable ? "unavailable" : ""}
                  >
                    <input
                      type="checkbox"
                      disabled={!line.vehicleAvailable}
                      checked={draft.lines.includes(line.code)}
                      onChange={() =>
                        onDraft((current) => ({
                          ...current,
                          lines: toggleValue(current.lines, line.code),
                        }))
                      }
                    />
                    <span>
                      {line.code}
                      {line.mode === "tram" ? " · tram" : ""}
                    </span>
                    {!line.vehicleAvailable && <small>Unavailable</small>}
                  </label>
                ))}
              </div>
            </details>
          ))}
        </>
      ) : (
        <div className="all-vehicles-note">
          <strong>All vehicles selected</strong>
          <p>
            Matched routes, other lines, and unresolved trip IDs will all be
            retained for the selected carriers and areas.
          </p>
        </div>
      )}
      <div className="apply-card">
        <button
          className="primary"
          disabled={invalid || loading}
          onClick={onApply}
        >
          {loading ? "Loading…" : "Apply filters"}
        </button>
        {invalid && (
          <p>
            Select at least one map area and carrier
            {draft.vehicleMode === "configured"
              ? ", plus one available line"
              : ""}
            .
          </p>
        )}
        {dirty && !invalid && (
          <p>Filters changed. The map still shows the last applied query.</p>
        )}
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {data && (
        <div className="loaded-summary">
          <strong>{data.metadata.counts.observations.toLocaleString()}</strong>{" "}
          loaded observations
          <small>
            {data.metadata.counts.matchedObservations.toLocaleString()}{" "}
            route-matched ·{" "}
            {data.metadata.counts.unmatchedObservations.toLocaleString()}{" "}
            unresolved retained
          </small>
        </div>
      )}
    </>
  );
}

function DetailsPanel({
  vehicle,
  visible,
  data,
}: {
  vehicle: (Observation & { age: number; stale: boolean }) | null;
  visible: boolean;
  data: Dataset | null;
}) {
  if (!vehicle)
    return (
      <>
        <span className="eyebrow">VEHICLE INSPECTOR</span>
        <h1>Details</h1>
        <div className="details-empty">
          Click any vehicle marker to inspect its latest loaded report.
        </div>
      </>
    );
  const rows: [string, React.ReactNode][] = [
    [
      "Status",
      visible
        ? "Visible at replay time"
        : "No longer visible at this replay time",
    ],
    [
      "Operator",
      `${data?.metadata.operators[vehicle.operatorId] ?? vehicle.operatorId} (${vehicle.operatorId})`,
    ],
    ["Vehicle", vehicle.vehicleId],
    ["Public line", vehicle.route?.line ?? "Unresolved"],
    ["Internal route", vehicle.route?.routeId ?? "Unresolved"],
    ["Mode", vehicle.route?.mode ?? "Unknown"],
    ["Direction", vehicle.route?.directionId || "Not supplied"],
    ["Trip", vehicle.tripId || "Not supplied"],
    ["Stop", vehicle.stopId || "Not supplied"],
    ["Route match", vehicle.routeMatchStatus ?? "unmatched"],
    ["Layer", vehicle.isFocus ? "Configured focus" : "Context / all vehicles"],
    [
      "Scheduled stop",
      vehicle.schedule?.scheduledTime
        ? formatStamp(vehicle.schedule.scheduledTime)
        : "Not available",
    ],
    [
      "Reported difference",
      vehicle.schedule?.reportedStopDifferenceSeconds == null
        ? "Not available"
        : `${vehicle.schedule.reportedStopDifferenceSeconds >= 0 ? "+" : ""}${Math.round(vehicle.schedule.reportedStopDifferenceSeconds / 60)} min`,
    ],
    [
      "Coordinates",
      `${vehicle.latitude.toFixed(6)}, ${vehicle.longitude.toFixed(6)}`,
    ],
    ["Geohash", vehicle.geohash ?? "Not supplied"],
    ["Report time", formatStamp(vehicle.timestamp)],
    ["Receipt time", formatStamp(vehicle.receivedTimestamp)],
    ["Report age", `${Math.max(0, Math.floor(vehicle.age))} seconds`],
  ];
  return (
    <>
      <span className="eyebrow">VEHICLE INSPECTOR</span>
      <h1>Vehicle {vehicle.vehicleId}</h1>
      {!visible && (
        <div className="visibility-warning">
          The marker expired or left the selected areas. These are its last
          loaded details.
        </div>
      )}
      <dl className="details-grid">
        {rows.map(([label, value]) => (
          <React.Fragment key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </React.Fragment>
        ))}
      </dl>
    </>
  );
}
