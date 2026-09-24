import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import {
  jsonRequest,
  LatestRequest,
  loadBunchingWeek,
  loadBunchingWeekSummary,
  loadLineDay,
  loadSelection,
  loadVehicleDay,
  loadWorkspaceCatalog,
} from "./api";
import {
  detectMapBunching,
  type BunchingDiagram,
  type MapBunchingCandidate,
} from "./bunching";
import { BunchingWeekModal } from "./BunchingWeekModal";
import { BunchingDiagramView, BunchingPanel } from "./BunchingPanel";
import {
  CAUSES,
  CORRIDOR_COLOR,
  fixOf,
  heat,
  loadFindings,
  problemTitle,
  simWindow,
  stopLabel,
  type Findings,
  type FindingStop,
  type Problem,
} from "./findings";
import { FindingsBoard, FindingsPanel, type MapFocus } from "./FindingsPanel";
import "./findings.css";
import type { SimRun } from "./sim";
import { SimulatePanel, SimulationView, type SimPreset } from "./SimulatePanel";
import { geohashBounds } from "./geohash";
import { LineAnalysisModal } from "./LineAnalysisModal";
import { TrafficControl } from "./TrafficControl";
import { useRouteTraffic } from "./useRouteTraffic";
import { trafficBand, trafficDescription, unknownTraffic } from "./traffic";
import {
  clock,
  colors,
  indexObservations,
  keyOf,
  snapshot,
  type Dataset,
  type Observation,
} from "./replay";
import {
  buildBunchingTimeline,
  type BunchingTimelinePoint,
} from "./replayDock";
import {
  defaultFilters,
  filtersEqual,
  resizeDayWindow,
  shiftDayWindow,
  toggleValue,
  windowDurationMinutes,
} from "./workspaceState";
import type {
  BunchingWeek,
  BunchingWeekSummary,
  CatalogRoute,
  LineDay,
  RouteGeometry,
  VehicleDay,
  VehicleFilters,
  WorkspaceCatalog,
  WorkspacePreset,
} from "./workspaceTypes";

type Tab = "findings" | "bunching" | "simulate" | "explore";
type ExploreView = "routes" | "details";
const TABS: { id: Tab; label: string; hint: string }[] = [
  {
    id: "findings",
    label: "Findings",
    hint: "Where, when and why buses bunch every week, and what to change",
  },
  {
    id: "bunching",
    label: "Risk prediction",
    hint: "Predicts which buses are about to bunch on a recorded day, and tests holding them",
  },
  {
    id: "simulate",
    label: "Simulation",
    hint: "Replays a real day with one change to the timetable and shows what it would have changed",
  },
  {
    id: "explore",
    label: "Explore data",
    hint: "GPS replay of the network, planned routes, weekly signals and vehicle details",
  },
];
const DEFAULT_SCENARIO: Record<Problem["cause"], string> = {
  dispatch: "D2",
  turnaround: "T2-2",
  road: "M-90",
};
const AREA_COLOR = "#b45309";
const located = (stop: FindingStop | null | undefined) =>
  !!stop && stop.lat !== null && stop.lon !== null;
const latLng = (stop: FindingStop): L.LatLngTuple => [stop.lat!, stop.lon!];
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
const formatDuration = (seconds: number) => {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
};
const formatDifference = (seconds: number | null) => {
  if (seconds == null) return "No scheduled time";
  if (Math.abs(seconds) < 30) return "on time";
  const value = Math.round(Math.abs(seconds) / 60);
  return `${value} min ${seconds > 0 ? "after" : "before"} schedule`;
};
const routeColor = (route: CatalogRoute | RouteGeometry, index = 0) => {
  const value = route.route_color;
  if (value && value !== "#277a91")
    return value.startsWith("#") ? value : `#${value}`;
  return palette[index % palette.length];
};

export function UnifiedWorkspace() {
  const [tab, setTab] = useState<Tab>("findings");
  const [exploreView, setExploreView] = useState<ExploreView>("routes");
  const [findings, setFindings] = useState<Findings | null>(null);
  const [findingsError, setFindingsError] = useState("");
  const [showBoard, setShowBoard] = useState(true);
  const [focus, setFocus] = useState<MapFocus>(null);
  const [simPreset, setSimPreset] = useState<SimPreset | null>(null);
  const [dockOpen, setDockOpen] = useState(true);
  const [statusOpen, setStatusOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
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
  const [vehicleDay, setVehicleDay] = useState<VehicleDay | null>(null);
  const [loadingVehicleDay, setLoadingVehicleDay] = useState(false);
  const [vehicleDayError, setVehicleDayError] = useState("");
  const [selectedRouteKeys, setSelectedRouteKeys] = useState<string[]>([]);
  const [routeGeometry, setRouteGeometry] = useState<RouteGeometry[]>([]);
  const [routeSearch, setRouteSearch] = useState("");
  const [showStops, setShowStops] = useState(false);
  const [showTraffic, setShowTraffic] = useState(false);
  const traffic = useRouteTraffic(showTraffic, selectedRouteKeys);
  const trafficData = traffic.data;
  const [showReferenceZones, setShowReferenceZones] = useState(false);
  const [showAreaBoundaries, setShowAreaBoundaries] = useState(true);
  const [clickableZones, setClickableZones] = useState(false);
  const [mapSettingsOpen, setMapSettingsOpen] = useState(false);
  const [customizeLines, setCustomizeLines] = useState(false);
  const [customizeRoutes, setCustomizeRoutes] = useState(false);
  const [tileError, setTileError] = useState(false);
  const [showBunchingCandidates, setShowBunchingCandidates] = useState(true);
  const [focusedLine, setFocusedLine] = useState<string | null>(null);
  const [analysisEditorOpen, setAnalysisEditorOpen] = useState(false);
  const [lineAnalysisTarget, setLineAnalysisTarget] = useState<{
    operatorId: string;
    line: string;
  } | null>(null);
  const [lineAnalysis, setLineAnalysis] = useState<LineDay | null>(null);
  const [loadingLineAnalysis, setLoadingLineAnalysis] = useState(false);
  const [lineAnalysisError, setLineAnalysisError] = useState("");
  const [weekAnalysisTarget, setWeekAnalysisTarget] = useState<{
    operatorId: string;
    line: string;
  } | null>(null);
  const [weekAnalysis, setWeekAnalysis] = useState<BunchingWeek | null>(null);
  const [loadingWeekAnalysis, setLoadingWeekAnalysis] = useState(false);
  const [weekAnalysisError, setWeekAnalysisError] = useState("");
  const [weekSummary, setWeekSummary] = useState<BunchingWeekSummary | null>(
    null,
  );
  const [loadingWeekSummary, setLoadingWeekSummary] = useState(false);
  const [weekSummaryError, setWeekSummaryError] = useState("");
  // New simulation/bunching diagram state (from bunching-prediction branch)
  const [bunching, setBunching] = useState<BunchingDiagram | null>(null);
  const [showDiagram, setShowDiagram] = useState(true);
  const [simRun, setSimRun] = useState<SimRun | null>(null);
  const [showSim, setShowSim] = useState(true);
  const [simPick, setSimPick] = useState<{ code: string } | null>(null);

  const mapNode = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const areaLayer = useRef<L.LayerGroup | null>(null);
  const referenceLayer = useRef<L.LayerGroup | null>(null);
  const routeLayer = useRef<L.LayerGroup | null>(null);
  const stopLayer = useRef<L.LayerGroup | null>(null);
  const bunchingLayer = useRef<L.LayerGroup | null>(null);
  const findingsLayer = useRef<L.LayerGroup | null>(null);
  const markers = useRef(new Map<string, L.CircleMarker>());
  const catalogRequest = useRef(new LatestRequest());
  const vehicleRequest = useRef(new LatestRequest());
  const geometryRequest = useRef(new LatestRequest());
  const vehicleDayRequest = useRef(new LatestRequest());
  const lineAnalysisRequest = useRef(new LatestRequest());
  const weekAnalysisRequest = useRef(new LatestRequest());
  const weekSummaryRequest = useRef(new LatestRequest());
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
  const activeInspectedLine = focusedLine;

  const mapBunchingCandidates = useMemo(() => {
    const all = detectMapBunching(visible);
    if (!activeInspectedLine) return all;
    return all.sort((a, b) => {
      const aMatch = a.line === activeInspectedLine ? 1 : 0;
      const bMatch = b.line === activeInspectedLine ? 1 : 0;
      return bMatch - aMatch;
    });
  }, [visible, activeInspectedLine]);

  const bunchedVehicleKeys = useMemo(
    () =>
      new Set(
        mapBunchingCandidates.flatMap((candidate) => [
          keyOf(candidate.first),
          keyOf(candidate.second),
        ]),
      ),
    [mapBunchingCandidates],
  );

  const bunchingTimeline = useMemo(
    () => buildBunchingTimeline(data, activeInspectedLine),
    [data, activeInspectedLine],
  );

  const filtersDirty = !filtersEqual(applied, draft);
  const filterSelectionInvalid =
    !draft.areas.length ||
    !draft.operators.length ||
    (draft.vehicleMode === "configured" && !draft.lines.length);
  const windowDuration = windowDurationMinutes(draft.start, draft.end);
  const windowSelectionInvalid = windowDuration <= 0 || windowDuration > 4 * 60;

  function focusBunchingCandidate(candidate: MapBunchingCandidate) {
    setSelectedVehicleKey(keyOf(candidate.first));
    setLastSelectedVehicle(candidate.first);
    setFocusedLine(candidate.line);
    if (map.current) {
      const lat1 = candidate.first.latitude;
      const lon1 = candidate.first.longitude;
      const lat2 = candidate.second.latitude;
      const lon2 = candidate.second.longitude;
      map.current.fitBounds(
        [
          [lat1, lon1],
          [lat2, lon2],
        ],
        { padding: [90, 90], maxZoom: 17 },
      );
    }
  }

  async function applyFilters(next = draft) {
    const nextDuration = windowDurationMinutes(next.start, next.end);
    if (
      !next.areas.length ||
      !next.operators.length ||
      nextDuration <= 0 ||
      nextDuration > 4 * 60
    )
      return;
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
        const defaultRouteKeys =
          result.presets
            .find((preset) => preset.id === result.defaultPresetId)
            ?.lines.flatMap((line) => line.routeKeys) ?? [];
        setCatalog(result);
        setDraft(next);
        setSelectedRouteKeys(defaultRouteKeys);
        setRouteGeometry([]);
        if (firstCatalog.current) {
          firstCatalog.current = false;
          void applyFilters(next);
        }
      })
      .catch((reason) => setError((reason as Error).message))
      .finally(() => setLoadingCatalog(false));
    return () => request.cancel();
    // The catalog intentionally reloads only when the selected date changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.date]);

  useEffect(() => {
    const request = weekSummaryRequest.current;
    setLoadingWeekSummary(true);
    setWeekSummary(null);
    setWeekSummaryError("");
    void request
      .run((signal) => loadBunchingWeekSummary(draft.date, signal))
      .then((result) => {
        if (result) setWeekSummary(result);
      })
      .catch((reason) => setWeekSummaryError((reason as Error).message))
      .finally(() => setLoadingWeekSummary(false));
    return () => request.cancel();
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
    const request = vehicleDayRequest.current;
    if (!selectedVehicleKey || !applied?.date) {
      setVehicleDay(null);
      setVehicleDayError("");
      return;
    }
    const [operatorId, vehicleId] = JSON.parse(selectedVehicleKey) as [
      string,
      string,
    ];
    setLoadingVehicleDay(true);
    setVehicleDay(null);
    setVehicleDayError("");
    void request
      .run((signal) =>
        loadVehicleDay(applied.date, operatorId, vehicleId, signal),
      )
      .then((result) => {
        if (result) setVehicleDay(result);
      })
      .catch((reason) => setVehicleDayError((reason as Error).message))
      .finally(() => setLoadingVehicleDay(false));
    return () => request.cancel();
  }, [selectedVehicleKey, applied?.date]);

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
    bunchingLayer.current = L.layerGroup().addTo(instance);
    findingsLayer.current = L.layerGroup().addTo(instance);
    L.control.zoom({ position: "bottomright" }).addTo(instance);
    // Light basemap (Stadia "Alidade Smooth"), from the LightThemeMap branch
    L.tileLayer(
      "https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png",
      {
        attribution: "&copy; OpenStreetMap contributors &copy; Stadia Maps",
        maxZoom: 20,
      },
    )
      .on("tileerror", () => setTileError(true))
      .addTo(instance);
    const markerStore = markers.current;
    const resizeObserver = new ResizeObserver(() => instance.invalidateSize());
    resizeObserver.observe(mapNode.current);
    return () => {
      resizeObserver.disconnect();
      instance.remove();
      map.current = null;
      markerStore.clear();
    };
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() =>
      map.current?.invalidateSize(),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [analysisEditorOpen, sidebarCollapsed, dockOpen, tab]);

  // the Findings tab shows the week's answer; live vehicles and areas belong to the other tabs
  const onFindings = tab === "findings";

  useEffect(() => {
    const controller = new AbortController();
    loadFindings(controller.signal)
      .then(setFindings)
      .catch((reason) => {
        if (!controller.signal.aborted)
          setFindingsError((reason as Error).message);
      });
    return () => controller.abort();
  }, []);

  function testFix(problem: Problem) {
    const window = simWindow(problem);
    setDraft((current) => ({ ...current, ...window }));
    setSimPreset({
      line: problem.line,
      direction: problem.direction,
      scenario: problem.tested?.scenario ?? DEFAULT_SCENARIO[problem.cause],
    });
    setShowBoard(false);
    setTab("simulate");
  }

  // Findings map: problem terminals, the worst stops and shared stretches; the focused one in detail
  useEffect(() => {
    const layer = findingsLayer.current;
    const instance = map.current;
    if (!layer || !instance) return;
    layer.clearLayers();
    if (!onFindings || !findings) return;
    const base = findings.headline.weekdayRate;
    const bounds: L.LatLngTuple[] = [];

    findings.hotspots.filter(located).forEach((stop) =>
      L.circleMarker(latLng(stop), {
        radius: 3 + Math.sqrt(stop.bunchedPerWeekday) * 1.4,
        color: "#7a1f1f",
        weight: 1,
        fillColor: heat(stop.rate, base),
        fillOpacity: focus ? 0.35 : 0.85,
      })
        .bindTooltip(
          `<b>${stopLabel(stop)}</b><br>${stop.bunchedPerWeekday} bunched bus visits per weekday (${(stop.rate * 100).toFixed(1)} %)<br>lines ${stop.lines.join(", ")} · worst around ${stop.peakHour}:00`,
        )
        .addTo(layer),
    );

    findings.corridors.slice(0, 5).forEach((corridor, index) => {
      const active = focus?.kind === "corridor" && focus.index === index;
      if (focus && !active) return;
      const points = corridor.sharedStops.filter(located).map(latLng);
      if (points.length < 2) return;
      L.polyline(points, {
        color: CORRIDOR_COLOR,
        weight: active ? 7 : 4,
        opacity: active ? 0.95 : 0.6,
        dashArray: active ? undefined : "6 6",
      })
        .bindTooltip(
          `<b>Lines ${corridor.lines.join(" + ")}</b> share ${corridor.sharedStops.length} stops<br>${Math.round(corridor.eventsPerWeekday)} times per weekday they run together · ${corridor.peakHours.slice(0, 2).join(", ")}`,
        )
        .addTo(layer);
      if (active) {
        bounds.push(...points);
        corridor.sharedStops.filter(located).forEach((stop) =>
          L.circleMarker(latLng(stop), {
            radius: 5,
            color: "#fff",
            weight: 2,
            fillColor: CORRIDOR_COLOR,
            fillOpacity: 1,
          })
            .bindTooltip(stopLabel(stop))
            .addTo(layer),
        );
      }
    });

    (findings.areas ?? []).forEach((area, index) => {
      const active = focus?.kind === "area" && focus.index === index;
      if (focus && !active) return;
      L.circle([area.lat, area.lon], {
        radius: 380,
        color: AREA_COLOR,
        weight: active ? 3 : 2,
        dashArray: "6 5",
        fillColor: AREA_COLOR,
        fillOpacity: active ? 0.18 : 0.1,
      })
        .bindTooltip(
          `<b>Area ${index + 1}: around ${area.stops[0] ? stopLabel(area.stops[0]) : "here"}</b><br>${area.ratio}× more catch-ups than expected · ${area.days}/5 weekdays<br>${area.lines} lines · worst ${area.peakHours.slice(0, 2).join(", ")}`,
        )
        .on("click", () => setFocus({ kind: "area", index }))
        .addTo(layer);
      if (active) {
        bounds.push([area.lat, area.lon]);
        area.stops.filter(located).forEach((stop) => {
          bounds.push(latLng(stop));
          L.circleMarker(latLng(stop), {
            radius: 6,
            color: "#fff",
            weight: 2,
            fillColor: AREA_COLOR,
            fillOpacity: 1,
          })
            .bindTooltip(
              `${stopLabel(stop)} · bunching starts here ${stop.onsets}× in the week`,
            )
            .addTo(layer);
        });
      }
    });

    findings.problems.forEach((problem, index) => {
      const active = focus?.kind === "problem" && focus.index === index;
      if (focus && !active) return;
      const cause = CAUSES[problem.cause];
      if (active) {
        // the route in the problem hours, coloured stop by stop by how often buses bunch there
        const route = problem.profile.filter(located);
        for (let i = 1; i < route.length; i += 1)
          L.polyline([latLng(route[i - 1]), latLng(route[i])], {
            color: heat(route[i].rate, base),
            weight: 8,
            opacity: 0.95,
          })
            .bindTooltip(
              `${stopLabel(route[i])} · ${(route[i].rate * 100).toFixed(1)} % bunched in ${problem.hours.join(", ")}`,
            )
            .addTo(layer);
        bounds.push(...route.map(latLng));
        problem.stretch.filter(located).forEach((stop, rank) =>
          L.marker(latLng(stop), {
            icon: L.divIcon({
              className: "worst-pin",
              html: `<span>${rank + 1}</span>`,
              iconSize: [22, 22],
            }),
          })
            .bindTooltip(
              `<b>${stopLabel(stop)}</b><br>${(stop.rate * 100).toFixed(0)} % of visits bunched in ${problem.hours.join(", ")}, on ${stop.days}/5 weekdays`,
            )
            .addTo(layer),
        );
      }
      if (!located(problem.terminal)) return;
      bounds.push(latLng(problem.terminal!));
      L.marker(latLng(problem.terminal!), {
        icon: L.divIcon({
          className: "terminal-pin",
          html: `<span style="background:${cause.color}">${problem.line}</span>`,
          iconSize: [40, 22],
          iconAnchor: [20, 11],
        }),
        zIndexOffset: active ? 1000 : 0,
      })
        .bindTooltip(
          `<b>${problemTitle(problem)}</b><br>Terminal · ${problem.hours.join(", ")}<br>${cause.label}. Best fix: ${fixOf(problem).name}`,
        )
        .on("click", () => setFocus({ kind: "problem", index }))
        .addTo(layer);
    });
    if (focus && bounds.length)
      instance.fitBounds(L.latLngBounds(bounds), {
        padding: [60, 60],
        maxZoom: 15,
      });
    else if (!focus) {
      const all = findings.problems
        .map((p) => p.terminal)
        .filter(located)
        .map((stop) => latLng(stop!));
      if (all.length)
        instance.fitBounds(L.latLngBounds(all), { padding: [80, 80] });
    }
  }, [onFindings, findings, focus]);

  useEffect(() => {
    const layer = areaLayer.current;
    if (!layer || !catalog) return;
    layer.clearLayers();
    if (!showAreaBoundaries || onFindings) return;
    catalog.areas.forEach((area) => {
      const pending = draft.areas.includes(area.id);
      const active = applied?.areas.includes(area.id) ?? false;
      const changed = pending !== active;
      const rectangle = L.rectangle(geohashBounds(area.id), {
        color: changed ? "#f59e0b" : active ? "#277a91" : "#4a6873",
        weight: changed ? 1.5 : active ? 1 : 0.75,
        opacity: changed ? 0.6 : active ? 0.25 : 0.1,
        dashArray: pending ? undefined : "3 4",
        fillColor: changed ? "#f59e0b" : active ? "#277a91" : "transparent",
        fillOpacity: changed ? 0.04 : active ? 0.015 : 0,
        interactive: clickableZones,
      });
      if (clickableZones) {
        rectangle.bindTooltip(
          `${area.id} · ${area.name}<br>${pending ? "Enabled" : "Disabled"}${changed ? " · pending Apply" : ""}`,
        );
        rectangle.on("click", () =>
          setDraft((current) => ({
            ...current,
            areas: toggleValue(current.areas, area.id),
          })),
        );
      }
      rectangle.addTo(layer);
    });
  }, [
    catalog,
    draft.areas,
    applied?.areas,
    showAreaBoundaries,
    clickableZones,
    onFindings,
  ]);

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
          opacity: 0.22,
          fillOpacity: 0.01,
          interactive: clickableZones,
        });
        if (clickableZones) {
          rectangle.bindTooltip(
            `${zone.presetName} · ${zone.name} · ${zone.hash}`,
          );
        }
        rectangle.addTo(layer);
      });
  }, [catalog, showReferenceZones, clickableZones]);

  useEffect(() => {
    if (!activeInspectedLine || !catalog) return;
    const lineRouteKeys = catalog.routes
      .filter((r) => r.line_short_name === activeInspectedLine)
      .map((r) => r.key);
    if (lineRouteKeys.length > 0) {
      setSelectedRouteKeys((current) => {
        const missing = lineRouteKeys.filter((k) => !current.includes(k));
        return missing.length > 0 ? [...current, ...missing] : current;
      });
    }
  }, [activeInspectedLine, catalog]);

  useEffect(() => {
    routeLayer.current?.clearLayers();
    stopLayer.current?.clearLayers();
    if (onFindings) return;
    routeGeometry
      .filter((route) => selectedRouteKeys.includes(route.key))
      .forEach((route, routeIndex) => {
        const isInspected =
          activeInspectedLine != null &&
          (route.line_short_name === activeInspectedLine ||
            route.route_long_name.includes(activeInspectedLine));
        const color = routeColor(route, routeIndex);
        const congestion = trafficData?.routes.find(
          (item) => item.key === route.key,
        );

        if (isInspected) {
          route.shapes.forEach((shape) =>
            L.polyline(shape.points, {
              color: "#f59e0b",
              weight: 9,
              opacity: 0.4,
              interactive: false,
            }).addTo(routeLayer.current!),
          );
        }

        if (showTraffic && congestion) {
          congestion.sections.forEach((section) => {
            const tooltip = document.createElement("div");
            tooltip.textContent = `${isInspected ? "★ " : ""}${route.line_short_name} · ${route.route_long_name} · ${trafficDescription(section)}`;
            L.polyline(section.points, {
              color: trafficBand(section.speedRatio).color,
              weight: isInspected ? 6 : 5,
              opacity: isInspected ? 1 : activeInspectedLine ? 0.3 : 0.95,
              dashArray: section.speedRatio == null ? "6 5" : undefined,
            })
              .bindTooltip(tooltip)
              .addTo(routeLayer.current!);
          });
        } else {
          route.shapes.forEach((shape) =>
            L.polyline(shape.points, {
              color: isInspected
                ? "#fbbf24"
                : showTraffic
                  ? unknownTraffic.color
                  : color,
              weight: isInspected ? 4.5 : activeInspectedLine ? 2.5 : 4,
              opacity: isInspected ? 1 : activeInspectedLine ? 0.25 : 0.78,
              dashArray: showTraffic && !isInspected ? "6 5" : undefined,
            })
              .bindTooltip(
                `${isInspected ? "★ " : ""}${route.line_short_name} · ${route.route_long_name}`,
              )
              .addTo(routeLayer.current!),
          );
        }

        if (showStops)
          route.stops.forEach((stop) =>
            L.circleMarker([stop.lat, stop.lon], {
              radius: isInspected ? 5 : 4,
              color: isInspected ? "#f59e0b" : "#173c48",
              weight: isInspected ? 2 : 1,
              fillColor: isInspected ? "#fef08a" : color,
              fillOpacity: isInspected ? 1 : 0.9,
            })
              .bindTooltip(`${stop.stop_name} · ${route.line_short_name}`)
              .addTo(stopLayer.current!),
          );
      });
  }, [
    routeGeometry,
    selectedRouteKeys,
    showStops,
    activeInspectedLine,
    showTraffic,
    trafficData,
    onFindings,
  ]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const shown = onFindings ? [] : visible;
    const currentKeys = new Set(shown.map(keyOf));
    markers.current.forEach((marker, key) => {
      if (!currentKeys.has(key)) {
        marker.remove();
        markers.current.delete(key);
      }
    });
    shown.forEach((vehicle) => {
      const key = keyOf(vehicle);
      const isBunched = bunchedVehicleKeys.has(key);
      const vehicleLine = vehicle.schedule?.line || vehicle.route?.line;
      const isLineMatch =
        activeInspectedLine != null && vehicleLine === activeInspectedLine;
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
        if (vehicleLine) setFocusedLine(vehicleLine);
        setTab("explore");
        setExploreView("details");
      });
      marker.setLatLng([vehicle.latitude, vehicle.longitude]);
      marker.setRadius(
        key === selectedVehicleKey
          ? 11
          : isBunched && isLineMatch
            ? 10
            : isBunched
              ? 9
              : isLineMatch
                ? 8
                : activeInspectedLine
                  ? 4
                  : vehicle.isFocus
                    ? 7
                    : 5,
      );
      marker.setStyle({
        color:
          key === selectedVehicleKey
            ? "#fff"
            : isBunched
              ? "#d63e35"
              : isLineMatch
                ? "#f59e0b"
                : "#173c48",
        weight:
          key === selectedVehicleKey ? 3 : isBunched ? 4 : isLineMatch ? 3 : 2,
        fillColor: colors[vehicle.operatorId] ?? "#788f98",
        fillOpacity: vehicle.stale
          ? 0.25
          : activeInspectedLine
            ? isLineMatch
              ? 1
              : 0.2
            : vehicle.isFocus
              ? 0.95
              : 0.5,
      });
      marker
        .unbindTooltip()
        .bindTooltip(
          `${data?.metadata.operators[vehicle.operatorId]} · ${vehicle.vehicleId}${vehicleLine ? ` · Line ${vehicleLine}` : ""}`,
        );
    });
  }, [
    visible,
    selectedVehicleKey,
    data,
    bunchedVehicleKeys,
    activeInspectedLine,
    onFindings,
  ]);

  useEffect(() => {
    const layer = bunchingLayer.current;
    if (!layer) return;
    layer.clearLayers();
    if (!showBunchingCandidates || onFindings) return;
    mapBunchingCandidates.forEach((candidate) => {
      const first: L.LatLngExpression = [
        candidate.first.latitude,
        candidate.first.longitude,
      ];
      const second: L.LatLngExpression = [
        candidate.second.latitude,
        candidate.second.longitude,
      ];
      const details = `<strong>Possible bunching · Line ${candidate.line}</strong><br>Vehicles #${candidate.first.vehicleId} and #${candidate.second.vehicleId}<br>${candidate.distanceMeters}m separation · ${formatDuration(candidate.observedGapSeconds)} gap (planned ${formatDuration(candidate.plannedGapSeconds)})<br><em>Click to focus on pair</em>`;
      L.polyline([first, second], {
        color: "#d63e35",
        weight: 3,
        opacity: 0.9,
        dashArray: "5 5",
        interactive: false,
      }).addTo(layer);
      [first, second].forEach((position) =>
        L.circleMarker(position, {
          radius: 14,
          color: "#d63e35",
          weight: 3,
          fill: false,
          opacity: 0.9,
          interactive: false,
        }).addTo(layer),
      );
      const midpoint: [number, number] = [
        (candidate.first.latitude + candidate.second.latitude) / 2,
        (candidate.first.longitude + candidate.second.longitude) / 2,
      ];
      L.circleMarker(midpoint, {
        radius: 8,
        color: "#fff",
        weight: 2,
        fillColor: "#d63e35",
        fillOpacity: 1,
        interactive: true,
      })
        .bindTooltip(details)
        .on("click", () => focusBunchingCandidate(candidate))
        .addTo(layer);
    });
  }, [mapBunchingCandidates, showBunchingCandidates, onFindings]);

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

  const openLineAnalysis = (operatorId: string, line: string) => {
    const target = { operatorId, line };
    setLineAnalysisTarget(target);
    setLineAnalysis(null);
    setLineAnalysisError("");
    setLoadingLineAnalysis(true);
    void lineAnalysisRequest.current
      .run((signal) => loadLineDay(draft.date, operatorId, line, signal))
      .then((result) => {
        if (result) setLineAnalysis(result);
      })
      .catch((reason) => setLineAnalysisError((reason as Error).message))
      .finally(() => setLoadingLineAnalysis(false));
  };

  const closeLineAnalysis = () => {
    lineAnalysisRequest.current.cancel();
    setLineAnalysisTarget(null);
    setLineAnalysis(null);
    setLineAnalysisError("");
    setLoadingLineAnalysis(false);
  };

  const openWeekAnalysis = (operatorId: string, line: string) => {
    const target = { operatorId, line };
    setWeekAnalysisTarget(target);
    setWeekAnalysis(null);
    setWeekAnalysisError("");
    setLoadingWeekAnalysis(true);
    void weekAnalysisRequest.current
      .run((signal) => loadBunchingWeek(draft.date, operatorId, line, signal))
      .then((result) => {
        if (result) setWeekAnalysis(result);
      })
      .catch((reason) => setWeekAnalysisError((reason as Error).message))
      .finally(() => setLoadingWeekAnalysis(false));
  };

  const closeWeekAnalysis = () => {
    weekAnalysisRequest.current.cancel();
    setWeekAnalysisTarget(null);
    setWeekAnalysis(null);
    setWeekAnalysisError("");
    setLoadingWeekAnalysis(false);
  };

  return (
    <div className={`workspace ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="sidebar" aria-label="Analysis panels">
        <header className="workspace-header">
          <div className="brand">
            <span className="brandmark">R</span> RouteMaxxing{" "}
            <span className="edition">PROJECT 07</span>
          </div>
          <p>Bus bunching in Lisbon · CARRIS · Challenge 7</p>
          <button
            type="button"
            className="sidebar-collapse-button"
            onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
            aria-label={
              sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"
            }
            aria-expanded={!sidebarCollapsed}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <span aria-hidden="true">{sidebarCollapsed ? "›" : "‹"}</span>
          </button>
        </header>
        <nav
          className="sidebar-tabs findings-tabs"
          aria-label="Workspace panels"
        >
          {TABS.map((item, index) => (
            <button
              key={item.id}
              className={tab === item.id ? "active" : ""}
              onClick={() => setTab(item.id)}
              title={item.hint}
            >
              <small>{index + 1}</small>
              {item.label}
              {item.id === "explore" && selectedVehicleKey ? " •" : ""}
            </button>
          ))}
        </nav>
        <p className="tab-hint">
          {TABS.find((item) => item.id === tab)?.hint}
          {tab !== "findings" &&
            " · date and time window: in the bar under the map"}
        </p>

        <div className="sidebar-content">
          {tab === "findings" && (
            <FindingsPanel
              findings={findings}
              error={findingsError}
              focus={focus}
              onFocus={(value) => {
                setFocus(value);
                if (value) setShowBoard(false);
              }}
              onOpenPlan={() => setShowBoard(true)}
              onTest={testFix}
            />
          )}
          {tab === "explore" && (
            <div className="explore-switch two" role="tablist">
              {(["routes", "details"] as ExploreView[]).map((view) => (
                <button
                  key={view}
                  role="tab"
                  aria-selected={exploreView === view}
                  className={exploreView === view ? "active" : ""}
                  onClick={() => setExploreView(view)}
                >
                  {view === "routes"
                    ? "Network & routes"
                    : `Vehicle details${selectedVehicleKey ? " •" : ""}`}
                </button>
              ))}
            </div>
          )}
          {tab === "explore" && exploreView === "routes" && (
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
              onAnalyzeLine={openLineAnalysis}
              onAnalyzeWeek={openWeekAnalysis}
              weekSummary={weekSummary}
              loadingWeekSummary={loadingWeekSummary}
              weekSummaryError={weekSummaryError}
            />
          )}
          {tab === "bunching" && (
            <BunchingPanel
              date={draft.date}
              start={draft.start}
              end={draft.end}
              result={bunching}
              onResult={(value) => {
                setBunching(value);
                setShowDiagram(true);
              }}
            />
          )}
          {tab === "simulate" && (
            <SimulatePanel
              date={draft.date}
              start={draft.start}
              end={draft.end}
              result={simRun}
              pick={simPick}
              preset={simPreset}
              onPresetDone={() => setSimPreset(null)}
              onResult={(value) => {
                setSimRun(value);
                setShowSim(true);
              }}
            />
          )}
          {tab === "explore" && exploreView === "details" && (
            <DetailsPanel
              vehicle={inspectedVehicle}
              visible={!!visibleSelected}
              data={data}
              vehicleDay={vehicleDay}
              loadingVehicleDay={loadingVehicleDay}
              vehicleDayError={vehicleDayError}
              activeInspectedLine={activeInspectedLine}
              onFocusLine={(line) => setFocusedLine(line)}
            />
          )}
        </div>
      </aside>
      <main className="map-shell">
        <div className="map-viewport">
          <div className="map" ref={mapNode} />
          {onFindings && findings && (
            <>
              {showBoard ? (
                <FindingsBoard
                  findings={findings}
                  onClose={() => setShowBoard(false)}
                  onFocus={setFocus}
                  onTest={testFix}
                />
              ) : (
                <>
                  <button
                    className="bunching-show"
                    onClick={() => setShowBoard(true)}
                  >
                    Show the action plan
                  </button>
                  <div className="findings-legend">
                    <b>Map</b>
                    <span>
                      <i className="dot" /> stops where buses bunch every
                      weekday (size = how often)
                    </span>
                    {Object.values(CAUSES).map((cause) => (
                      <span key={cause.label}>
                        <i
                          className="pin"
                          style={{ background: cause.color }}
                        />
                        terminal · {cause.label.toLowerCase()}
                      </span>
                    ))}
                    <span>
                      <i
                        className="dot"
                        style={{
                          background: "#b453091a",
                          border: `2px dashed ${AREA_COLOR}`,
                        }}
                      />
                      area where buses catch up more than expected
                    </span>
                    <span>
                      <i
                        className="bar"
                        style={{ background: CORRIDOR_COLOR }}
                      />
                      stretch shared by two lines that run together
                    </span>
                    {focus && (
                      <button onClick={() => setFocus(null)}>
                        Show all problems
                      </button>
                    )}
                  </div>
                </>
              )}
            </>
          )}
          {!onFindings && (
            <div className={`map-status${statusOpen ? "" : " collapsed"}`}>
              <button
                type="button"
                className="map-status-header"
                onClick={() => setStatusOpen((open) => !open)}
                aria-expanded={statusOpen}
                title={statusOpen ? "Collapse this box" : "Expand this box"}
              >
                <span>
                  {data
                    ? `${visible.length} vehicles visible`
                    : "Apply vehicle filters to begin"}
                  <small>
                    {statusOpen
                      ? `${selectedRouteKeys.length} planned route variants shown`
                      : data
                        ? `${mapBunchingCandidates.length} possible bunching ${mapBunchingCandidates.length === 1 ? "pair" : "pairs"} at ${clock(time)}`
                        : ""}
                  </small>
                </span>
                <i className="collapse-caret" aria-hidden="true">
                  {statusOpen ? "▴" : "▾"}
                </i>
              </button>
              {data && statusOpen && (
                <div className="bunching-collapsible-section">
                  <button
                    className={`bunching-map-toggle ${mapBunchingCandidates.length ? "detected" : ""}`}
                    aria-pressed={showBunchingCandidates}
                    onClick={() => setShowBunchingCandidates((value) => !value)}
                  >
                    <span aria-hidden="true" />
                    {mapBunchingCandidates.length
                      ? `${mapBunchingCandidates.length} possible bunching ${mapBunchingCandidates.length === 1 ? "pair" : "pairs"}`
                      : "No possible bunching pairs"}
                    <em>{showBunchingCandidates ? "Hide" : "Show"}</em>
                  </button>

                  {showBunchingCandidates && (
                    <div className="bunching-collapsed-list">
                      {mapBunchingCandidates.length > 0 ? (
                        <div className="live-bunching-strip vertical">
                          <div className="live-bunching-badge">
                            <span className="pulse-dot" />
                            <strong>
                              {mapBunchingCandidates.length} Bunching{" "}
                              {mapBunchingCandidates.length === 1
                                ? "Pair"
                                : "Pairs"}
                            </strong>{" "}
                            at {clock(time)}:
                          </div>
                          <div className="live-bunching-list vertical-list">
                            {mapBunchingCandidates.map((candidate) => {
                              const isSelected =
                                selectedVehicleKey === keyOf(candidate.first) ||
                                selectedVehicleKey === keyOf(candidate.second);
                              return (
                                <button
                                  key={candidate.id}
                                  type="button"
                                  className={`bunching-pair-chip ${isSelected ? "selected" : ""}`}
                                  onClick={() =>
                                    focusBunchingCandidate(candidate)
                                  }
                                  title={`Line ${candidate.line}: Bus ${candidate.first.vehicleId} & Bus ${candidate.second.vehicleId} · ${candidate.distanceMeters}m separation · Click to focus map`}
                                >
                                  <span className="line-pill">
                                    Line {candidate.line}
                                  </span>
                                  <span className="bus-names">
                                    #{candidate.first.vehicleId} ↔ #
                                    {candidate.second.vehicleId}
                                  </span>
                                  <span className="bunch-dist">
                                    {candidate.distanceMeters}m (
                                    {formatDuration(
                                      candidate.observedGapSeconds,
                                    )}
                                    )
                                  </span>
                                  <span className="bunch-action">Focus ↗</span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ) : bunchingTimeline.some((h) => h.count > 0) ? (
                        <div className="live-bunching-strip quiet vertical">
                          <span className="no-bunch-text">
                            No bunching at {clock(time)}.
                          </span>
                          {(() => {
                            const nextBunch =
                              bunchingTimeline.find(
                                (h) => h.count > 0 && h.t > time + 30000,
                              ) || bunchingTimeline.find((h) => h.count > 0);
                            if (!nextBunch) return null;
                            return (
                              <button
                                type="button"
                                className="jump-bunch-btn"
                                onClick={() => {
                                  setTime(nextBunch.t);
                                  setPlaying(false);
                                }}
                              >
                                Jump to bunching at {clock(nextBunch.t)} (
                                {nextBunch.count} pair
                                {nextBunch.count !== 1 ? "s" : ""}) →
                              </button>
                            );
                          })()}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          {!onFindings && (
            <div className="map-settings-control">
              <button
                type="button"
                className={`map-settings-trigger ${mapSettingsOpen ? "active" : ""} ${filtersDirty ? "dirty" : ""}`}
                onClick={() => setMapSettingsOpen((value) => !value)}
                title="Open Map Display & Filter Settings"
              >
                <svg
                  viewBox="0 0 24 24"
                  width="14"
                  height="14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
                <span className="trigger-title">Map Settings</span>
                <span className="trigger-badge">
                  {draft.lines.length
                    ? `${draft.lines.length} lines`
                    : `${draft.operators.length} carriers`}{" "}
                  · {draft.areas.length} regions
                </span>
                {filtersDirty && (
                  <span
                    className="trigger-dirty-dot"
                    title="Pending filter changes"
                  />
                )}
              </button>
            </div>
          )}
          {mapSettingsOpen && !onFindings && (
            <MapSettingsPanel
              catalog={catalog}
              draft={draft}
              dirty={filtersDirty}
              loading={loadingVehicles}
              invalid={filterSelectionInvalid}
              onDraft={setDraft}
              onApply={() => void applyFilters()}
              onClose={() => setMapSettingsOpen(false)}
              customizeLines={customizeLines}
              onToggleCustomizeLines={(val) => {
                setCustomizeLines(val);
                if (!val && catalog) {
                  const opLines = getOperatorsWithLines(catalog);
                  const recommended = opLines
                    .filter((op) => draft.operators.includes(op.operator.id))
                    .flatMap((op) => op.recommendedLines);
                  setDraft((curr) => ({
                    ...curr,
                    lines: recommended,
                  }));
                }
              }}
              customizeRoutes={customizeRoutes}
              onToggleCustomizeRoutes={setCustomizeRoutes}
              selectedRouteKeys={selectedRouteKeys}
              onSetRouteKeys={setSelectedRouteKeys}
              onClearRoutes={() => setSelectedRouteKeys([])}
              showStops={showStops}
              onShowStops={setShowStops}
              showReferenceZones={showReferenceZones}
              onShowReferenceZones={setShowReferenceZones}
              showAreaBoundaries={showAreaBoundaries}
              onShowAreaBoundaries={setShowAreaBoundaries}
              clickableZones={clickableZones}
              onToggleClickableZones={setClickableZones}
              showTraffic={showTraffic}
              onShowTraffic={setShowTraffic}
              traffic={traffic}
            />
          )}
          {tileError && (
            <div className="tilewarning">
              Background tiles are unavailable; data layers still work.
            </div>
          )}
          {tab === "bunching" &&
            bunching &&
            (showDiagram ? (
              <BunchingDiagramView
                result={bunching}
                onClose={() => setShowDiagram(false)}
              />
            ) : (
              <button
                className="bunching-show"
                onClick={() => setShowDiagram(true)}
              >
                Show time–space diagram
              </button>
            ))}
          {tab === "simulate" &&
            simRun &&
            (showSim ? (
              <SimulationView
                run={simRun}
                onPick={(code) => setSimPick({ code })}
                onClose={() => setShowSim(false)}
              />
            ) : (
              <button
                className="bunching-show"
                onClick={() => setShowSim(true)}
              >
                Show simulation
              </button>
            ))}
        </div>
        {data && !onFindings && (
          <section
            className={`timeline ${analysisEditorOpen && dockOpen ? "expanded" : ""}${dockOpen ? "" : " collapsed"}`}
            aria-label="Replay and bunching controls"
          >
            <div className="replay-context-row">
              <div className="replay-scope">
                <button
                  type="button"
                  className="dock-toggle"
                  onClick={() => setDockOpen((open) => !open)}
                  aria-expanded={dockOpen}
                  title={
                    dockOpen
                      ? "Hide the replay timeline"
                      : "Show the replay timeline"
                  }
                >
                  {dockOpen ? "▾" : "▴"}
                </button>
                <span className="replay-kicker">Possible bunching pairs</span>
                {activeInspectedLine ? (
                  <button
                    type="button"
                    className="replay-line-chip"
                    onClick={() => setFocusedLine(null)}
                    title="Return graph and map emphasis to the whole network"
                  >
                    Line {activeInspectedLine} <span aria-hidden="true">×</span>
                  </button>
                ) : (
                  <strong>Network</strong>
                )}
              </div>
              <div className="replay-transport">
                <span className="replay-current-time">{clock(time)}</span>
                <button
                  type="button"
                  className="replay-play-button"
                  aria-label={playing ? "Pause replay" : "Play replay"}
                  title={playing ? "Pause replay" : "Play replay"}
                  onClick={() => {
                    if (time >= data.metadata.endTimestamp)
                      setTime(data.metadata.startTimestamp);
                    setPlaying((value) => !value);
                  }}
                >
                  <span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span>
                </button>
                <div className="replay-speed-buttons" aria-label="Replay speed">
                  {[1, 10, 30, 60].map((value) => (
                    <button
                      type="button"
                      key={value}
                      className={speed === value ? "active" : ""}
                      aria-pressed={speed === value}
                      onClick={() => setSpeed(value)}
                    >
                      {value}×
                    </button>
                  ))}
                </div>
              </div>
              <button
                type="button"
                className={`window-summary ${filtersDirty ? "pending" : ""}`}
                onClick={() => {
                  setDockOpen(true);
                  setAnalysisEditorOpen((open) => !dockOpen || !open);
                }}
                aria-expanded={analysisEditorOpen}
              >
                <span>
                  {draft.date} · {draft.start}–
                  {draft.end === "00:00" ? "24:00" : draft.end}
                </span>
                <small>
                  {filtersDirty ? "Pending changes" : "Loaded window"}
                </small>
                <span className="window-summary-chevron" aria-hidden="true">
                  {analysisEditorOpen ? "▾" : "▴"}
                </span>
              </button>
            </div>

            {analysisEditorOpen && dockOpen && (
              <AnalysisWindowEditor
                catalog={catalog}
                filters={draft}
                dirty={filtersDirty}
                loading={loadingVehicles || loadingCatalog}
                invalid={filterSelectionInvalid || windowSelectionInvalid}
                error={error}
                onChange={setDraft}
                onApply={() => void applyFilters()}
              />
            )}

            {dockOpen && (
              <BunchingTimelineGraph
                timeline={bunchingTimeline}
                time={time}
                line={activeInspectedLine}
                startTimestamp={data.metadata.startTimestamp}
                endTimestamp={data.metadata.endTimestamp}
                onSeek={(timestamp) => {
                  setPlaying(false);
                  setTime(timestamp);
                }}
              />
            )}
          </section>
        )}
      </main>
      {lineAnalysisTarget && (
        <LineAnalysisModal
          target={lineAnalysisTarget}
          analysis={lineAnalysis}
          loading={loadingLineAnalysis}
          error={lineAnalysisError}
          workspaceStart={applied?.start ?? draft.start}
          workspaceEnd={applied?.end ?? draft.end}
          onClose={closeLineAnalysis}
        />
      )}
      {weekAnalysisTarget && (
        <BunchingWeekModal
          target={weekAnalysisTarget}
          week={weekAnalysis}
          loading={loadingWeekAnalysis}
          error={weekAnalysisError}
          onClose={closeWeekAnalysis}
        />
      )}
    </div>
  );
}

function AnalysisWindowEditor({
  catalog,
  filters,
  dirty,
  loading,
  invalid,
  error,
  onChange,
  onApply,
}: {
  catalog: WorkspaceCatalog | null;
  filters: VehicleFilters;
  dirty: boolean;
  loading: boolean;
  invalid: boolean;
  error: string;
  onChange: React.Dispatch<React.SetStateAction<VehicleFilters>>;
  onApply(): void;
}) {
  const duration = windowDurationMinutes(filters.start, filters.end);
  const updateWindow = (window: { start: string; end: string }) =>
    onChange((current) => ({ ...current, ...window }));

  return (
    <section className="analysis-window-editor" aria-label="Analysis window">
      <label className="window-field date-field">
        <span>Operational day</span>
        <select
          value={filters.date}
          onChange={(event) =>
            onChange((current) => ({ ...current, date: event.target.value }))
          }
        >
          {(catalog?.dates ?? [filters.date]).map((date) => (
            <option key={date}>{date}</option>
          ))}
        </select>
      </label>
      <label className="window-field">
        <span>Start</span>
        <input
          type="time"
          step={15 * 60}
          value={filters.start}
          onChange={(event) =>
            onChange((current) => ({ ...current, start: event.target.value }))
          }
        />
      </label>
      <label className="window-field">
        <span>End</span>
        <input
          type="time"
          step={15 * 60}
          value={filters.end}
          onChange={(event) =>
            onChange((current) => ({ ...current, end: event.target.value }))
          }
        />
      </label>
      <div className="window-shift" aria-label="Move analysis window">
        <span>Move window</span>
        <div>
          <button
            type="button"
            onClick={() =>
              updateWindow(shiftDayWindow(filters.start, filters.end, -1))
            }
            aria-label="Move window earlier"
          >
            ← Earlier
          </button>
          <button
            type="button"
            onClick={() =>
              updateWindow(shiftDayWindow(filters.start, filters.end, 1))
            }
            aria-label="Move window later"
          >
            Later →
          </button>
        </div>
      </div>
      <div className="window-presets" aria-label="Window duration">
        <span>Duration</span>
        <div>
          {[30, 60, 120, 240].map((minutes) => (
            <button
              type="button"
              key={minutes}
              className={duration === minutes ? "active" : ""}
              onClick={() =>
                updateWindow(resizeDayWindow(filters.start, minutes))
              }
            >
              {minutes < 60 ? `${minutes}m` : `${minutes / 60}h`}
            </button>
          ))}
        </div>
      </div>
      <div className="window-apply-group">
        <span
          className={`window-state ${invalid ? "invalid" : dirty ? "pending" : "applied"}`}
        >
          {invalid
            ? "Choose a window up to 4 hours"
            : dirty
              ? "Changes are not loaded"
              : "Map matches this window"}
        </span>
        {error && <span className="window-error">{error}</span>}
        <button
          type="button"
          className="load-window-button"
          disabled={invalid || loading || !dirty}
          onClick={onApply}
        >
          {loading ? "Loading…" : "Load window"}
        </button>
      </div>
    </section>
  );
}

function BunchingTimelineGraph({
  timeline,
  time,
  line,
  startTimestamp,
  endTimestamp,
  onSeek,
}: {
  timeline: BunchingTimelinePoint[];
  time: number;
  line: string | null;
  startTimestamp: number;
  endTimestamp: number;
  onSeek(timestamp: number): void;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const width = 1000;
  const height = 72;
  const baseline = 64;
  const peak = Math.max(1, ...timeline.map((point) => point.count));
  const firstTimestamp = startTimestamp;
  const lastTimestamp = endTimestamp;
  const denominator = Math.max(1, timeline.length - 1);
  const xAt = (index: number) => (index / denominator) * width;
  const yAt = (count: number) => baseline - (count / peak) * 50;
  const points = timeline
    .map((point, index) => `${xAt(index)},${yAt(point.count)}`)
    .join(" ");
  const area = timeline.length
    ? `M0,${baseline} ${timeline
        .map((point, index) => `L${xAt(index)},${yAt(point.count)}`)
        .join(" ")} L${width},${baseline} Z`
    : "";
  const playhead =
    ((Math.max(firstTimestamp, Math.min(lastTimestamp, time)) -
      firstTimestamp) /
      Math.max(1, lastTimestamp - firstTimestamp)) *
    width;
  const hovered = hoveredIndex == null ? null : timeline[hoveredIndex];
  const color = line ? "#e28a00" : "#d9593f";

  const seekFromPosition = (clientX: number, element: SVGSVGElement) => {
    if (!timeline.length) return;
    const rect = element.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (clientX - rect.left) / rect.width),
    );
    const index = Math.round(fraction * denominator);
    onSeek(timeline[index].t);
  };

  return (
    <div className="bunching-graph-wrap">
      <div className="graph-time-labels" aria-hidden="true">
        <span>{clock(startTimestamp)}</span>
        <span>{clock(endTimestamp)}</span>
      </div>
      <svg
        className="bunching-graph"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="slider"
        tabIndex={0}
        aria-valuemin={firstTimestamp}
        aria-valuemax={lastTimestamp}
        aria-valuenow={time}
        aria-label={`${line ? `Line ${line}` : "Network"} possible bunching pairs. Click or use arrow keys to change replay time.`}
        onClick={(event) =>
          seekFromPosition(event.clientX, event.currentTarget)
        }
        onMouseMove={(event) => {
          if (!timeline.length) return;
          const rect = event.currentTarget.getBoundingClientRect();
          const fraction = Math.max(
            0,
            Math.min(1, (event.clientX - rect.left) / rect.width),
          );
          setHoveredIndex(Math.round(fraction * denominator));
        }}
        onMouseLeave={() => setHoveredIndex(null)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const currentIndex = timeline.reduce(
            (nearest, point, index) =>
              Math.abs(point.t - time) < Math.abs(timeline[nearest].t - time)
                ? index
                : nearest,
            0,
          );
          const nextIndex = Math.max(
            0,
            Math.min(
              timeline.length - 1,
              currentIndex + (event.key === "ArrowRight" ? 1 : -1),
            ),
          );
          onSeek(timeline[nextIndex].t);
        }}
      >
        <defs>
          <linearGradient id="replayBunchingArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.48" />
            <stop offset="100%" stopColor={color} stopOpacity="0.04" />
          </linearGradient>
        </defs>
        <line x1="0" y1="14" x2={width} y2="14" className="graph-grid-line" />
        <line x1="0" y1="39" x2={width} y2="39" className="graph-grid-line" />
        <line
          x1="0"
          y1={baseline}
          x2={width}
          y2={baseline}
          className="graph-baseline"
        />
        {area && <path d={area} fill="url(#replayBunchingArea)" />}
        {points && (
          <polyline
            points={points}
            fill="none"
            stroke={color}
            strokeWidth="2.5"
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />
        )}
        <line
          x1={playhead}
          y1="4"
          x2={playhead}
          y2={baseline}
          className="graph-playhead"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {!timeline.some((point) => point.count > 0) && (
        <span className="graph-empty-state">
          No possible pairs in this window
        </span>
      )}
      {hovered && (
        <span
          className="graph-tooltip"
          style={{
            left: `${Math.max(7, Math.min(93, (hoveredIndex! / denominator) * 100))}%`,
          }}
        >
          {clock(hovered.t)} · {hovered.count} pair
          {hovered.count === 1 ? "" : "s"}
        </span>
      )}
      <div className="graph-scrubber-row">
        <input
          className="replay-scrubber"
          type="range"
          min={startTimestamp}
          max={endTimestamp}
          step={1000}
          value={time}
          aria-label="Replay time"
          onChange={(event) => onSeek(Number(event.target.value))}
        />
      </div>
    </div>
  );
}

function getOperatorSortRank(id: string): number {
  switch (id) {
    case "IA9T6":
      return 1; // Carris Lisbon
    case "LA77N":
      return 2; // Carris Metropolitana Area 1
    case "BNA17":
      return 3; // Carris Metropolitana Area 2
    case "YA15B":
      return 4; // Carris Metropolitana Area 3
    case "A2L1N":
      return 5; // Carris Metropolitana Area 4
    case "HF16N":
      return 6; // MobiCascais
    default:
      return 100;
  }
}

type OperatorCategory = "carris" | "metropolitana" | "mobicascais" | "other";

function getOperatorMeta(id: string, name: string) {
  switch (id) {
    case "IA9T6":
      return {
        category: "carris" as OperatorCategory,
        groupTitle: "CARRIS Lisbon (Urban Network)",
        displayName: "CARRIS Lisbon",
        sub: "Urban bus & tram lines",
        badge: "Carris",
        badgeClass: "badge-carris",
      };
    case "LA77N":
      return {
        category: "metropolitana" as OperatorCategory,
        groupTitle: "Carris Metropolitana (4 Operational Areas)",
        displayName: "Carris Metropolitana · Area 1",
        sub: "Noroeste (Amadora, Cascais, Oeiras, Sintra)",
        badge: "Area 1",
        badgeClass: "badge-cm1",
      };
    case "BNA17":
      return {
        category: "metropolitana" as OperatorCategory,
        groupTitle: "Carris Metropolitana (4 Operational Areas)",
        displayName: "Carris Metropolitana · Area 2",
        sub: "Nordeste (Loures, Odivelas, Mafra, Vila Franca de Xira)",
        badge: "Area 2",
        badgeClass: "badge-cm2",
      };
    case "YA15B":
      return {
        category: "metropolitana" as OperatorCategory,
        groupTitle: "Carris Metropolitana (4 Operational Areas)",
        displayName: "Carris Metropolitana · Area 3",
        sub: "Sudoeste (Almada, Seixal, Sesimbra)",
        badge: "Area 3",
        badgeClass: "badge-cm3",
      };
    case "A2L1N":
      return {
        category: "metropolitana" as OperatorCategory,
        groupTitle: "Carris Metropolitana (4 Operational Areas)",
        displayName: "Carris Metropolitana · Area 4",
        sub: "Sudeste (Alcochete, Barreiro, Moita, Montijo, Palmela, Setúbal)",
        badge: "Area 4",
        badgeClass: "badge-cm4",
      };
    case "HF16N":
      return {
        category: "mobicascais" as OperatorCategory,
        groupTitle: "MobiCascais (Municipal Network)",
        displayName: "MobiCascais",
        sub: "Cascais municipal transit network",
        badge: "Cascais",
        badgeClass: "badge-mobi",
      };
    default:
      return {
        category: "other" as OperatorCategory,
        groupTitle: "Other Transit Operators",
        displayName: name,
        sub: id,
        badge: "Other",
        badgeClass: "badge-other",
      };
  }
}

function getOperatorsWithLines(catalog: WorkspaceCatalog | null) {
  if (!catalog) return [];
  const sorted = [...catalog.operators].sort((first, second) => {
    const rankDiff =
      getOperatorSortRank(first.id) - getOperatorSortRank(second.id);
    if (rankDiff !== 0) return rankDiff;
    return first.name.localeCompare(second.name);
  });

  return sorted.map((operator) => {
    const meta = getOperatorMeta(operator.id, operator.name);
    const presetLines = catalog.presets
      .filter(
        (p) =>
          p.operatorAgencyIds.includes(operator.id) ||
          p.operators.some((o) => o.id === operator.id),
      )
      .flatMap((p) => p.lines);

    const otherRouteCodes = Array.from(
      new Set(
        catalog.routes
          .filter((r) => r.agency_id === operator.id)
          .map((r) => r.line_short_name),
      ),
    ).filter((code) => !presetLines.some((p) => p.code === code));

    const lines = [
      ...presetLines.map((p) => ({
        code: p.code,
        mode: p.mode,
        isPreset: true,
        available: p.vehicleAvailable,
      })),
      ...otherRouteCodes.map((code) => ({
        code,
        mode: "bus",
        isPreset: false,
        available: true,
      })),
    ];

    const recommendedLines = presetLines
      .filter((p) => p.vehicleAvailable)
      .map((p) => p.code);

    return {
      operator,
      meta,
      lines,
      recommendedLines,
    };
  });
}

type MapSettingsPanelProps = {
  catalog: WorkspaceCatalog | null;
  draft: VehicleFilters;
  dirty: boolean;
  loading: boolean;
  invalid: boolean;
  onDraft: React.Dispatch<React.SetStateAction<VehicleFilters>>;
  onApply(): void;
  onClose(): void;
  customizeLines: boolean;
  onToggleCustomizeLines(val: boolean): void;
  customizeRoutes: boolean;
  onToggleCustomizeRoutes(val: boolean): void;
  selectedRouteKeys: string[];
  onSetRouteKeys: React.Dispatch<React.SetStateAction<string[]>>;
  onClearRoutes(): void;
  showStops: boolean;
  onShowStops(val: boolean): void;
  showReferenceZones: boolean;
  onShowReferenceZones(val: boolean): void;
  showAreaBoundaries: boolean;
  onShowAreaBoundaries(val: boolean): void;
  clickableZones: boolean;
  onToggleClickableZones(val: boolean): void;
  showTraffic: boolean;
  onShowTraffic(val: boolean): void;
  traffic: ReturnType<typeof useRouteTraffic>;
};

function MapSettingsPanel({
  catalog,
  draft,
  dirty,
  loading,
  invalid,
  onDraft,
  onApply,
  onClose,
  customizeLines,
  onToggleCustomizeLines,
  customizeRoutes,
  onToggleCustomizeRoutes,
  selectedRouteKeys,
  onSetRouteKeys,
  onClearRoutes,
  showStops,
  onShowStops,
  showReferenceZones,
  onShowReferenceZones,
  showAreaBoundaries,
  onShowAreaBoundaries,
  clickableZones,
  onToggleClickableZones,
  showTraffic,
  onShowTraffic,
  traffic,
}: MapSettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<
    "vehicles" | "regions" | "routes" | "overlays"
  >("routes");
  const [routeSearch, setRouteSearch] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        const trigger = document.querySelector(".map-settings-trigger");
        if (trigger && trigger.contains(e.target as Node)) return;
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [onClose]);

  if (!catalog) return null;

  const operatorsWithLines = getOperatorsWithLines(catalog);

  const sortedPresets = [...catalog.presets].sort((a, b) => {
    const aRank = a.operatorAgencyIds?.[0]
      ? getOperatorSortRank(a.operatorAgencyIds[0])
      : 50;
    const bRank = b.operatorAgencyIds?.[0]
      ? getOperatorSortRank(b.operatorAgencyIds[0])
      : 50;
    return aRank - bRank;
  });

  const categoriesOrder: OperatorCategory[] = [
    "carris",
    "metropolitana",
    "mobicascais",
    "other",
  ];

  const categoryLabels: Record<
    OperatorCategory,
    { title: string; badge: string; desc: string }
  > = {
    carris: {
      title: "CARRIS Lisbon",
      badge: "Urban",
      desc: "City bus & historic tram network",
    },
    metropolitana: {
      title: "Carris Metropolitana",
      badge: "4 Areas",
      desc: "Suburban regional network divided into 4 operating lots",
    },
    mobicascais: {
      title: "MobiCascais",
      badge: "Cascais",
      desc: "Municipal network of Cascais",
    },
    other: {
      title: "Other Transit Operators",
      badge: "Other",
      desc: "Additional passenger transport operators",
    },
  };

  return (
    <div
      ref={panelRef}
      className="map-settings-panel"
      role="dialog"
      aria-label="Map Display and Filter Settings"
    >
      <div className="map-settings-header">
        <div>
          <h3>Map & Filter Settings</h3>
          <p className="settings-subtitle">
            Configure visible vehicles, lines, regions, and routes
          </p>
        </div>
        <button
          type="button"
          className="settings-close-btn"
          onClick={onClose}
          aria-label="Close settings"
        >
          ✕
        </button>
      </div>

      <div className="map-settings-nav-tabs">
        <button
          type="button"
          className={activeTab === "vehicles" ? "active" : ""}
          onClick={() => setActiveTab("vehicles")}
        >
          Vehicles & Lines
        </button>
        <button
          type="button"
          className={activeTab === "regions" ? "active" : ""}
          onClick={() => setActiveTab("regions")}
        >
          Regions ({draft.areas.length})
        </button>
        <button
          type="button"
          className={activeTab === "routes" ? "active" : ""}
          onClick={() => setActiveTab("routes")}
        >
          Routes (
          {
            new Set(
              catalog.routes
                .filter((r) => selectedRouteKeys.includes(r.key))
                .map((r) => r.line_short_name),
            ).size
          }
          )
        </button>
        <button
          type="button"
          className={activeTab === "overlays" ? "active" : ""}
          onClick={() => setActiveTab("overlays")}
        >
          Overlays
        </button>
      </div>

      <div className="map-settings-body">
        {activeTab === "vehicles" && (
          <div className="settings-section">
            <div className="customize-lines-switch-banner">
              <div className="switch-info">
                <strong>Customize bus lines</strong>
                <p>
                  {customizeLines
                    ? "Select from all lines across the network"
                    : "Showing configured bus lines. Turn on to select from all available lines."}
                </p>
              </div>
              <label className="toggle-switch-ui">
                <input
                  type="checkbox"
                  checked={customizeLines}
                  onChange={(e) => onToggleCustomizeLines(e.target.checked)}
                />
                <span className="slider-round" />
              </label>
            </div>

            <div className="operators-categories-wrapper">
              {categoriesOrder.map((catKey) => {
                const opsInCat = operatorsWithLines.filter(
                  (op) => op.meta.category === catKey,
                );
                if (!opsInCat.length) return null;

                return (
                  <div key={catKey} className="operator-category-group">
                    <div className="category-group-header">
                      <span className={`category-badge-tag ${catKey}`}>
                        {categoryLabels[catKey].badge}
                      </span>
                      <div className="category-header-text">
                        <strong>{categoryLabels[catKey].title}</strong>
                        <small>{categoryLabels[catKey].desc}</small>
                      </div>
                      <span className="category-group-count">
                        {opsInCat.length}{" "}
                        {opsInCat.length === 1 ? "carrier" : "carriers"}
                      </span>
                    </div>

                    <div className="operators-cards-list">
                      {opsInCat.map(
                        ({ operator, meta, lines, recommendedLines }) => {
                          const isOpChecked = draft.operators.includes(
                            operator.id,
                          );
                          const allOpLineCodes = lines.map((l) => l.code);
                          const checkedLinesCount = allOpLineCodes.filter((c) =>
                            draft.lines.includes(c),
                          ).length;

                          return (
                            <div
                              key={operator.id}
                              className={`operator-config-card ${isOpChecked ? "active" : ""}`}
                            >
                              <div className="operator-config-header">
                                <label className="operator-checkbox-label">
                                  <input
                                    type="checkbox"
                                    checked={isOpChecked}
                                    onChange={(e) => {
                                      const willCheck = e.target.checked;
                                      onDraft((current) => {
                                        const nextOps = willCheck
                                          ? Array.from(
                                              new Set([
                                                ...current.operators,
                                                operator.id,
                                              ]),
                                            )
                                          : current.operators.filter(
                                              (id) => id !== operator.id,
                                            );

                                        let nextLines = [...current.lines];
                                        if (customizeLines) {
                                          if (willCheck) {
                                            nextLines = Array.from(
                                              new Set([
                                                ...nextLines,
                                                ...allOpLineCodes,
                                              ]),
                                            );
                                          } else {
                                            nextLines = nextLines.filter(
                                              (c) =>
                                                !allOpLineCodes.includes(c),
                                            );
                                          }
                                        } else {
                                          if (willCheck) {
                                            nextLines = Array.from(
                                              new Set([
                                                ...nextLines,
                                                ...recommendedLines,
                                              ]),
                                            );
                                          } else {
                                            nextLines = nextLines.filter(
                                              (c) =>
                                                !allOpLineCodes.includes(c),
                                            );
                                          }
                                        }
                                        return {
                                          ...current,
                                          operators: nextOps,
                                          lines: nextLines,
                                          vehicleMode: "configured",
                                        };
                                      });
                                    }}
                                  />
                                  <div className="operator-title-meta">
                                    <div className="op-title-row">
                                      <strong className="op-name">
                                        {meta.displayName}
                                      </strong>
                                      <span
                                        className={`op-badge-pill ${meta.badgeClass}`}
                                      >
                                        {meta.badge}
                                      </span>
                                    </div>
                                    <span className="op-sub">
                                      {meta.sub} ·{" "}
                                      {operator.observations.toLocaleString()}{" "}
                                      reports
                                      {customizeLines && isOpChecked && (
                                        <span className="selected-lines-count">
                                          · {checkedLinesCount} of{" "}
                                          {allOpLineCodes.length} lines
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                </label>

                                {customizeLines && isOpChecked && (
                                  <div className="operator-quick-line-btns">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        onDraft((current) => ({
                                          ...current,
                                          operators: Array.from(
                                            new Set([
                                              ...current.operators,
                                              operator.id,
                                            ]),
                                          ),
                                          lines: Array.from(
                                            new Set([
                                              ...current.lines,
                                              ...allOpLineCodes,
                                            ]),
                                          ),
                                          vehicleMode: "configured",
                                        }));
                                      }}
                                    >
                                      All ({allOpLineCodes.length})
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        onDraft((current) => ({
                                          ...current,
                                          lines: current.lines.filter(
                                            (c) => !allOpLineCodes.includes(c),
                                          ),
                                          vehicleMode: "configured",
                                        }));
                                      }}
                                    >
                                      Clear
                                    </button>
                                  </div>
                                )}
                              </div>

                              {!customizeLines && (
                                <div className="operator-standard-notice">
                                  <span className="bullet-point" />
                                  <span>
                                    Configured lines (
                                    {recommendedLines.join(", ")})
                                  </span>
                                </div>
                              )}

                              {customizeLines && (
                                <div className="operator-lines-grid-section">
                                  <div className="lines-checkboxes-grid">
                                    {lines.map((line) => {
                                      const isLineChecked =
                                        draft.lines.includes(line.code);
                                      return (
                                        <label
                                          key={line.code}
                                          className={`line-checkbox-box ${isLineChecked ? "selected" : ""} ${!line.available ? "unavailable" : ""}`}
                                        >
                                          <input
                                            type="checkbox"
                                            checked={isLineChecked}
                                            onChange={(e) => {
                                              const checked = e.target.checked;
                                              onDraft((current) => {
                                                const nextLines = checked
                                                  ? [
                                                      ...current.lines,
                                                      line.code,
                                                    ]
                                                  : current.lines.filter(
                                                      (c) => c !== line.code,
                                                    );
                                                const anyOpLineActive =
                                                  allOpLineCodes.some((c) =>
                                                    c === line.code
                                                      ? checked
                                                      : current.lines.includes(
                                                          c,
                                                        ),
                                                  );
                                                const nextOps = anyOpLineActive
                                                  ? Array.from(
                                                      new Set([
                                                        ...current.operators,
                                                        operator.id,
                                                      ]),
                                                    )
                                                  : current.operators.filter(
                                                      (id) =>
                                                        id !== operator.id,
                                                    );
                                                return {
                                                  ...current,
                                                  lines: nextLines,
                                                  operators: nextOps,
                                                  vehicleMode: "configured",
                                                };
                                              });
                                            }}
                                          />
                                          <div className="line-box-label">
                                            <strong>{line.code}</strong>
                                          </div>
                                        </label>
                                      );
                                    })}
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        },
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {activeTab === "regions" && (
          <div className="settings-section">
            <div className="section-toolbar-row">
              <span>
                {draft.areas.length} of {catalog.areas.length} regions selected
              </span>
              <div className="toolbar-actions">
                <button
                  type="button"
                  onClick={() =>
                    onDraft((current) => ({
                      ...current,
                      areas: catalog.areas.map((a) => a.id),
                    }))
                  }
                >
                  Select all
                </button>
                <button
                  type="button"
                  onClick={() =>
                    onDraft((current) => ({ ...current, areas: [] }))
                  }
                >
                  Clear all
                </button>
              </div>
            </div>
            <div className="regions-checkboxes-grid">
              {catalog.areas.map((area) => {
                const isChecked = draft.areas.includes(area.id);
                return (
                  <label
                    key={area.id}
                    className={`region-select-card ${isChecked ? "selected" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() =>
                        onDraft((current) => ({
                          ...current,
                          areas: toggleValue(current.areas, area.id),
                        }))
                      }
                    />
                    <div className="region-card-info">
                      <strong className="region-code">{area.id}</strong>
                      <span className="region-name">{area.name}</span>
                      <small className="region-count">
                        {area.observations.toLocaleString()} vehicles
                      </small>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {activeTab === "routes" && (
          <div className="settings-section">
            <div className="customize-lines-switch-banner">
              <div className="switch-info">
                <strong>Customize bus lines</strong>
                <p>
                  {customizeRoutes
                    ? "Select from all routes across the full network"
                    : "Showing configured bus lines. Turn on to select other network routes."}
                </p>
              </div>
              <label className="toggle-switch-ui">
                <input
                  type="checkbox"
                  checked={customizeRoutes}
                  onChange={(e) => onToggleCustomizeRoutes(e.target.checked)}
                />
                <span className="slider-round" />
              </label>
            </div>

            <div className="route-search-container">
              <input
                type="text"
                placeholder="Search routes or lines across network (e.g. 728, Oriente)..."
                value={routeSearch}
                onChange={(e) => setRouteSearch(e.target.value)}
              />
            </div>

            <div className="section-toolbar-row">
              <span>
                {
                  new Set(
                    catalog.routes
                      .filter((r) => selectedRouteKeys.includes(r.key))
                      .map((r) => r.line_short_name),
                  ).size
                }{" "}
                bus lines selected
              </span>
              <div className="toolbar-actions">
                <button
                  type="button"
                  onClick={() => {
                    if (customizeRoutes) {
                      onSetRouteKeys(catalog.routes.map((r) => r.key));
                    } else {
                      const allPresetKeys = catalog.presets.flatMap((p) =>
                        p.lines.flatMap((l) => l.routeKeys),
                      );
                      onSetRouteKeys(allPresetKeys);
                    }
                  }}
                >
                  Select all
                </button>
                <button type="button" onClick={onClearRoutes}>
                  Clear
                </button>
              </div>
            </div>

            <div className="operators-categories-wrapper">
              {categoriesOrder.map((catKey) => {
                const opsInCat = operatorsWithLines.filter(
                  (op) => op.meta.category === catKey,
                );
                if (!opsInCat.length) return null;

                return (
                  <div key={catKey} className="operator-category-group">
                    <div className="category-group-header">
                      <span className={`category-badge-tag ${catKey}`}>
                        {categoryLabels[catKey].badge}
                      </span>
                      <div className="category-header-text">
                        <strong>{categoryLabels[catKey].title}</strong>
                        <small>{categoryLabels[catKey].desc}</small>
                      </div>
                      <span className="category-group-count">
                        {opsInCat.length}{" "}
                        {opsInCat.length === 1 ? "carrier" : "carriers"}
                      </span>
                    </div>

                    <div className="operators-cards-list">
                      {opsInCat.map(({ operator, meta }) => {
                        const term = routeSearch.trim().toLowerCase();

                        // Collect all preset lines for this operator
                        const opPresets = sortedPresets.filter((p) =>
                          p.operatorAgencyIds.includes(operator.id),
                        );
                        const presetLineItems = opPresets.flatMap(
                          (p) => p.lines,
                        );
                        const presetLineCodes = new Set(
                          presetLineItems.map((l) => l.code),
                        );

                        // Build other line items (only when customizing)
                        const otherLineItems: {
                          code: string;
                          routeKeys: string[];
                          planAvailable: boolean;
                        }[] = customizeRoutes
                          ? Array.from(
                              catalog.routes
                                .filter(
                                  (r) =>
                                    r.agency_id === operator.id &&
                                    !presetLineCodes.has(r.line_short_name),
                                )
                                .reduce<Map<string, string[]>>((acc, r) => {
                                  const list = acc.get(r.line_short_name) ?? [];
                                  list.push(r.key);
                                  acc.set(r.line_short_name, list);
                                  return acc;
                                }, new Map()),
                            ).map(([code, rkeys]) => ({
                              code,
                              routeKeys: rkeys,
                              planAvailable: true,
                            }))
                          : [];

                        const allLineItems = [
                          ...presetLineItems,
                          ...otherLineItems,
                        ];
                        const allRouteKeys = allLineItems.flatMap(
                          (l) => l.routeKeys,
                        );

                        // Search filter
                        const visibleLines = allLineItems.filter((l) => {
                          if (!term) return true;
                          const matchRoute = catalog.routes.find(
                            (r) =>
                              l.routeKeys.includes(r.key) ||
                              r.line_short_name === l.code,
                          );
                          return (
                            l.code.toLowerCase().includes(term) ||
                            (matchRoute?.route_long_name || "")
                              .toLowerCase()
                              .includes(term)
                          );
                        });

                        if (term && !visibleLines.length) return null;

                        const checkedLinesCount = allLineItems.filter(
                          (l) =>
                            l.routeKeys.length > 0 &&
                            l.routeKeys.every((k) =>
                              selectedRouteKeys.includes(k),
                            ),
                        ).length;
                        const isAllChecked =
                          allRouteKeys.length > 0 &&
                          allRouteKeys.every((k) =>
                            selectedRouteKeys.includes(k),
                          );
                        const isAnyChecked = allRouteKeys.some((k) =>
                          selectedRouteKeys.includes(k),
                        );

                        return (
                          <div
                            key={operator.id}
                            className={`operator-config-card ${isAnyChecked ? "active" : ""}`}
                          >
                            <div className="operator-config-header">
                              <label className="operator-checkbox-label">
                                <input
                                  type="checkbox"
                                  checked={isAllChecked}
                                  ref={(el) => {
                                    if (el)
                                      el.indeterminate =
                                        !isAllChecked && isAnyChecked;
                                  }}
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      onSetRouteKeys((curr) =>
                                        Array.from(
                                          new Set([...curr, ...allRouteKeys]),
                                        ),
                                      );
                                    } else {
                                      onSetRouteKeys((curr) =>
                                        curr.filter(
                                          (k) => !allRouteKeys.includes(k),
                                        ),
                                      );
                                    }
                                  }}
                                />
                                <div className="operator-title-meta">
                                  <div className="op-title-row">
                                    <strong className="op-name">
                                      {meta.displayName}
                                    </strong>
                                    <span
                                      className={`op-badge-pill ${meta.badgeClass}`}
                                    >
                                      {meta.badge}
                                    </span>
                                  </div>
                                  <span className="op-sub">
                                    {meta.sub}
                                    {customizeRoutes && isAnyChecked && (
                                      <span className="selected-lines-count">
                                        {" "}
                                        · {checkedLinesCount} of{" "}
                                        {allLineItems.length} lines
                                      </span>
                                    )}
                                  </span>
                                </div>
                              </label>

                              {customizeRoutes && isAnyChecked && (
                                <div className="operator-quick-line-btns">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      onSetRouteKeys((curr) =>
                                        Array.from(
                                          new Set([...curr, ...allRouteKeys]),
                                        ),
                                      )
                                    }
                                  >
                                    All ({allLineItems.length})
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      onSetRouteKeys((curr) =>
                                        curr.filter(
                                          (k) => !allRouteKeys.includes(k),
                                        ),
                                      )
                                    }
                                  >
                                    Clear
                                  </button>
                                </div>
                              )}
                            </div>

                            {!customizeRoutes && (
                              <div className="operator-standard-notice">
                                <span className="bullet-point" />
                                <span>
                                  Configured lines (
                                  {presetLineItems
                                    .map((l) => l.code)
                                    .join(", ")}
                                  )
                                </span>
                              </div>
                            )}

                            {customizeRoutes && (
                              <div className="operator-lines-grid-section">
                                <div className="lines-checkboxes-grid">
                                  {visibleLines.map((line) => {
                                    const isLineChecked =
                                      line.routeKeys.length > 0 &&
                                      line.routeKeys.every((k) =>
                                        selectedRouteKeys.includes(k),
                                      );
                                    const isLinePartial =
                                      !isLineChecked &&
                                      line.routeKeys.some((k) =>
                                        selectedRouteKeys.includes(k),
                                      );
                                    return (
                                      <label
                                        key={line.code}
                                        className={`line-checkbox-box ${isLineChecked ? "selected" : ""} ${!line.planAvailable ? "unavailable" : ""}`}
                                      >
                                        <input
                                          type="checkbox"
                                          disabled={!line.planAvailable}
                                          checked={isLineChecked}
                                          ref={(el) => {
                                            if (el)
                                              el.indeterminate = isLinePartial;
                                          }}
                                          onChange={(e) => {
                                            if (e.target.checked) {
                                              onSetRouteKeys((curr) =>
                                                Array.from(
                                                  new Set([
                                                    ...curr,
                                                    ...line.routeKeys,
                                                  ]),
                                                ),
                                              );
                                            } else {
                                              onSetRouteKeys((curr) =>
                                                curr.filter(
                                                  (k) =>
                                                    !line.routeKeys.includes(k),
                                                ),
                                              );
                                            }
                                          }}
                                        />
                                        <div className="line-box-label">
                                          <strong>{line.code}</strong>
                                        </div>
                                      </label>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              {customizeRoutes &&
                (() => {
                  const allPresetAgencyIds = new Set(
                    catalog.presets.flatMap((p) => p.operatorAgencyIds),
                  );
                  const term = routeSearch.trim().toLowerCase();
                  const nonPresetRoutesByCode = catalog.routes
                    .filter(
                      (r) =>
                        !allPresetAgencyIds.has(r.agency_id) &&
                        (!term ||
                          r.line_short_name.toLowerCase().includes(term) ||
                          r.route_long_name.toLowerCase().includes(term) ||
                          r.agency_name.toLowerCase().includes(term)),
                    )
                    .reduce<Map<string, { keys: string[] }>>((acc, r) => {
                      const entry = acc.get(r.line_short_name) ?? {
                        keys: [],
                      };
                      entry.keys.push(r.key);
                      acc.set(r.line_short_name, entry);
                      return acc;
                    }, new Map());

                  if (!nonPresetRoutesByCode.size) return null;

                  const nonPresetKeys = Array.from(
                    nonPresetRoutesByCode.values(),
                  ).flatMap((v) => v.keys);
                  const isAllNonPreset =
                    nonPresetKeys.length > 0 &&
                    nonPresetKeys.every((k) => selectedRouteKeys.includes(k));
                  const isAnyNonPreset = nonPresetKeys.some((k) =>
                    selectedRouteKeys.includes(k),
                  );

                  return (
                    <div className="operator-category-group">
                      <div className="category-group-header">
                        <span className="category-badge-tag other">OTHER</span>
                        <div className="category-header-text">
                          <strong>Other Transit Operators</strong>
                          <small>
                            Additional passenger transport operators
                          </small>
                        </div>
                      </div>
                      <div className="operators-cards-list">
                        <div
                          className={`operator-config-card ${isAnyNonPreset ? "active" : ""}`}
                        >
                          <div className="operator-config-header">
                            <label className="operator-checkbox-label">
                              <input
                                type="checkbox"
                                checked={isAllNonPreset}
                                ref={(el) => {
                                  if (el)
                                    el.indeterminate =
                                      !isAllNonPreset && isAnyNonPreset;
                                }}
                                onChange={() => {
                                  if (isAllNonPreset) {
                                    onSetRouteKeys((curr) =>
                                      curr.filter(
                                        (k) => !nonPresetKeys.includes(k),
                                      ),
                                    );
                                  } else {
                                    onSetRouteKeys((curr) =>
                                      Array.from(
                                        new Set([...curr, ...nonPresetKeys]),
                                      ),
                                    );
                                  }
                                }}
                              />
                              <div className="operator-title-meta">
                                <div className="op-title-row">
                                  <strong className="op-name">
                                    Other transit operators
                                  </strong>
                                </div>
                                <span className="op-sub">
                                  Regional rail, metro &amp; ferry routes
                                  {isAnyNonPreset && (
                                    <span className="selected-lines-count">
                                      {" "}
                                      · {nonPresetRoutesByCode.size} lines
                                    </span>
                                  )}
                                </span>
                              </div>
                            </label>
                            {isAnyNonPreset && (
                              <div className="operator-quick-line-btns">
                                <button
                                  type="button"
                                  onClick={() =>
                                    onSetRouteKeys((curr) =>
                                      Array.from(
                                        new Set([...curr, ...nonPresetKeys]),
                                      ),
                                    )
                                  }
                                >
                                  All ({nonPresetRoutesByCode.size})
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    onSetRouteKeys((curr) =>
                                      curr.filter(
                                        (k) => !nonPresetKeys.includes(k),
                                      ),
                                    )
                                  }
                                >
                                  Clear
                                </button>
                              </div>
                            )}
                          </div>
                          <div className="operator-lines-grid-section">
                            <div className="lines-checkboxes-grid">
                              {Array.from(nonPresetRoutesByCode.entries()).map(
                                ([code, { keys }]) => {
                                  const isChecked =
                                    keys.length > 0 &&
                                    keys.every((k) =>
                                      selectedRouteKeys.includes(k),
                                    );
                                  const isPartial =
                                    !isChecked &&
                                    keys.some((k) =>
                                      selectedRouteKeys.includes(k),
                                    );
                                  return (
                                    <label
                                      key={code}
                                      className={`line-checkbox-box ${isChecked ? "selected" : ""}`}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={isChecked}
                                        ref={(el) => {
                                          if (el) el.indeterminate = isPartial;
                                        }}
                                        onChange={(e) => {
                                          if (e.target.checked) {
                                            onSetRouteKeys((curr) =>
                                              Array.from(
                                                new Set([...curr, ...keys]),
                                              ),
                                            );
                                          } else {
                                            onSetRouteKeys((curr) =>
                                              curr.filter(
                                                (k) => !keys.includes(k),
                                              ),
                                            );
                                          }
                                        }}
                                      />
                                      <div className="line-box-label">
                                        <strong>{code}</strong>
                                      </div>
                                    </label>
                                  );
                                },
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })()}
            </div>
          </div>
        )}

        {activeTab === "overlays" && (
          <div className="settings-section">
            <div className="overlay-switches-list">
              <TrafficControl
                enabled={showTraffic}
                onChange={onShowTraffic}
                selectedCount={selectedRouteKeys.length}
                traffic={traffic}
              />
              <label className="overlay-option-card">
                <input
                  type="checkbox"
                  checked={showAreaBoundaries}
                  onChange={(e) => onShowAreaBoundaries(e.target.checked)}
                />
                <div className="overlay-text">
                  <strong>Area geofence boundaries</strong>
                  <p>Show faint boundary outlines for regions on the map</p>
                </div>
              </label>
              <label className="overlay-option-card">
                <input
                  type="checkbox"
                  checked={clickableZones}
                  onChange={(e) => onToggleClickableZones(e.target.checked)}
                />
                <div className="overlay-text">
                  <strong>Clickable boundaries on map</strong>
                  <p>
                    Allow clicking boundary rectangles to toggle regions (off by
                    default to prevent accidental clicks)
                  </p>
                </div>
              </label>
              <label className="overlay-option-card">
                <input
                  type="checkbox"
                  checked={showStops}
                  onChange={(e) => onShowStops(e.target.checked)}
                />
                <div className="overlay-text">
                  <strong>Representative bus stops</strong>
                  <p>Display circular stop dots along selected route lines</p>
                </div>
              </label>
              <label className="overlay-option-card">
                <input
                  type="checkbox"
                  checked={showReferenceZones}
                  onChange={(e) => onShowReferenceZones(e.target.checked)}
                />
                <div className="overlay-text">
                  <strong>Six-character configured zones</strong>
                  <p>Display reference preset zone outlines</p>
                </div>
              </label>
            </div>
          </div>
        )}
      </div>

      <div className="map-settings-footer-bar">
        <div
          className={`filter-state-hint ${invalid ? "invalid" : dirty ? "pending" : "applied"}`}
        >
          {invalid
            ? "⚠️ Select at least one region and one carrier/line"
            : dirty
              ? "● Filter changes waiting to be applied"
              : "✓ All filters applied to map"}
        </div>
        <div className="footer-button-group">
          <button type="button" className="close-panel-btn" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            className="primary apply-filters-btn"
            disabled={invalid || loading || !dirty}
            onClick={() => {
              onApply();
              onClose();
            }}
          >
            {loading ? "Loading…" : "Apply filters"}
          </button>
        </div>
      </div>
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
  weekSummary: BunchingWeekSummary | null;
  loadingWeekSummary: boolean;
  weekSummaryError: string;
  onSearch(value: string): void;
  onToggleKeys(keys: string[]): void;
  onClear(): void;
  onShowStops(value: boolean): void;
  onShowZones(value: boolean): void;
  onAnalyzeLine(operatorId: string, line: string): void;
  onAnalyzeWeek(operatorId: string, line: string): void;
};
function RoutesPanel({
  catalog,
  selectedKeys,
  search,
  filteredRoutes,
  showStops,
  showZones,
  weekSummary,
  loadingWeekSummary,
  weekSummaryError,
  onSearch,
  onToggleKeys,
  onClear,
  onShowStops,
  onShowZones,
  onAnalyzeLine,
  onAnalyzeWeek,
}: RoutesPanelProps) {
  if (!catalog) return <p className="muted">Loading date-valid routes…</p>;
  const summaryByLine = new Map(
    (weekSummary?.lines ?? []).map(
      (line) => [`${line.operatorId}:${line.line}`, line] as const,
    ),
  );
  const topLines = [...(weekSummary?.lines ?? [])]
    .filter((line) => line.candidateEpisodes > 0)
    .sort(
      (first, second) =>
        second.candidateEpisodes - first.candidateEpisodes ||
        first.line.localeCompare(second.line),
    )
    .slice(0, 8);
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
  routesByOperator.sort((first, second) => {
    const rankDiff =
      getOperatorSortRank(first.id) - getOperatorSortRank(second.id);
    if (rankDiff !== 0) return rankDiff;
    return first.name.localeCompare(second.name);
  });
  routesByOperator.forEach((group) =>
    group.routes.sort((first, second) => {
      const firstCount =
        summaryByLine.get(`${first.agency_id}:${first.line_short_name}`)
          ?.candidateEpisodes ?? -1;
      const secondCount =
        summaryByLine.get(`${second.agency_id}:${second.line_short_name}`)
          ?.candidateEpisodes ?? -1;
      return (
        secondCount - firstCount ||
        first.line_short_name.localeCompare(second.line_short_name)
      );
    }),
  );
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
        CARRIS Lisbon routes are shown by default. Route overlays remain
        independent from vehicle filters.
      </p>
      <section className="weekly-ranking">
        <div className="weekly-ranking-heading">
          <div>
            <span className="eyebrow">WEEKLY BUNCHING SIGNALS</span>
            <h2>Most candidates</h2>
          </div>
          {weekSummary && (
            <small>
              {weekSummary.weekStart}–{weekSummary.weekEnd}
            </small>
          )}
        </div>
        {loadingWeekSummary && <p className="muted">Loading weekly totals…</p>}
        {weekSummaryError && (
          <p className="coverage-warning">{weekSummaryError}</p>
        )}
        {!loadingWeekSummary && !weekSummaryError && !topLines.length && (
          <p className="muted">No precomputed weekly results are available.</p>
        )}
        {!!topLines.length && (
          <div className="weekly-ranking-list">
            {topLines.map((line, index) => (
              <button
                key={`${line.operatorId}:${line.line}`}
                onClick={() => onAnalyzeWeek(line.operatorId, line.line)}
                title={`Open the weekly evidence for line ${line.line}`}
              >
                <span className="weekly-rank">{index + 1}</span>
                <strong>{line.line}</strong>
                <span>{line.candidateEpisodes}</span>
                <small>{line.analyzedDays}/7 days</small>
              </button>
            ))}
          </div>
        )}
        <p className="weekly-ranking-note">
          Multi-stop investigation candidates. Counts are not normalized for how
          often each line runs.
        </p>
      </section>
      <h2>Configured groups</h2>
      <div className="preset-list">
        {catalog.presets.map((preset) => (
          <PresetRoutes
            key={preset.id}
            preset={preset}
            important={preset.id === catalog.defaultPresetId}
            open={false}
            selectedKeys={selectedKeys}
            onToggleKeys={onToggleKeys}
            onAnalyzeLine={onAnalyzeLine}
            onAnalyzeWeek={onAnalyzeWeek}
            summaryByLine={summaryByLine}
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
              <div
                className={`route-picker-item ${selectedKeys.includes(route.key) ? "selected" : ""}`}
                key={route.key}
              >
                <label>
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
                <div className="line-actions">
                  <WeeklyCount
                    value={summaryByLine.get(
                      `${route.agency_id}:${route.line_short_name}`,
                    )}
                  />
                  <button
                    className="analyze-line"
                    onClick={() =>
                      onAnalyzeLine(route.agency_id, route.line_short_name)
                    }
                  >
                    Day
                  </button>
                  <button
                    className="analyze-line"
                    onClick={() =>
                      onAnalyzeWeek(route.agency_id, route.line_short_name)
                    }
                  >
                    Week
                  </button>
                </div>
              </div>
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
  onAnalyzeLine,
  onAnalyzeWeek,
  summaryByLine,
}: {
  preset: WorkspacePreset;
  important: boolean;
  open: boolean;
  selectedKeys: string[];
  onToggleKeys(keys: string[]): void;
  onAnalyzeLine(operatorId: string, line: string): void;
  onAnalyzeWeek(operatorId: string, line: string): void;
  summaryByLine: Map<string, BunchingWeekSummary["lines"][number]>;
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
            <div
              key={line.code}
              className={!line.planAvailable ? "unavailable" : ""}
            >
              <label>
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
              <div className="line-actions">
                <WeeklyCount
                  value={summaryByLine.get(
                    `${preset.operatorAgencyIds[0]}:${line.code}`,
                  )}
                />
                <button
                  className="analyze-line"
                  disabled={!line.planAvailable}
                  onClick={() =>
                    onAnalyzeLine(preset.operatorAgencyIds[0], line.code)
                  }
                >
                  Day
                </button>
                <button
                  className="analyze-line"
                  disabled={!line.planAvailable}
                  onClick={() =>
                    onAnalyzeWeek(preset.operatorAgencyIds[0], line.code)
                  }
                >
                  Week
                </button>
              </div>
            </div>
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

function WeeklyCount({
  value,
}: {
  value?: BunchingWeekSummary["lines"][number];
}) {
  return (
    <span
      className={`weekly-count ${value ? "available" : "missing"}`}
      title={
        value
          ? `${value.candidateEpisodes} multi-stop candidates across ${value.analyzedDays}/7 analyzed days`
          : "This line has not been precomputed for the selected week"
      }
    >
      {value ? value.candidateEpisodes : "—"}
      <small>{value ? `${value.analyzedDays}/7` : "0/7"}</small>
    </span>
  );
}

function DetailsPanel({
  vehicle,
  visible,
  data,
  vehicleDay,
  loadingVehicleDay,
  vehicleDayError,
  activeInspectedLine,
  onFocusLine,
}: {
  vehicle: (Observation & { age: number; stale: boolean }) | null;
  visible: boolean;
  data: Dataset | null;
  vehicleDay: VehicleDay | null;
  loadingVehicleDay: boolean;
  vehicleDayError: string;
  activeInspectedLine?: string | null;
  onFocusLine?: (line: string) => void;
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
  const line = vehicle.route?.line || vehicle.schedule?.line;
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
    [
      "Public line",
      line ? (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <strong>Line {line}</strong>
          {onFocusLine && (
            <button
              type="button"
              onClick={() => onFocusLine(line)}
              style={{
                padding: "2px 7px",
                fontSize: "9.5px",
                fontWeight: 600,
                background:
                  activeInspectedLine === line ? "#d97706" : "#e2e8f0",
                color: activeInspectedLine === line ? "#fff" : "#1e293b",
                border: "1px solid #cbd5e1",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              {activeInspectedLine === line ? "Inspecting ★" : "Inspect Line"}
            </button>
          )}
        </span>
      ) : (
        "Unresolved"
      ),
    ],
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
  const importantGaps = vehicleDay
    ? [...vehicleDay.gaps]
        .sort((left, right) => right.durationSeconds - left.durationSeconds)
        .slice(0, 20)
    : [];
  const nearbyStops = vehicleDay
    ? [...vehicleDay.stopReports]
        .sort(
          (left, right) =>
            Math.abs(left.reportedTime - vehicle.timestamp) -
            Math.abs(right.reportedTime - vehicle.timestamp),
        )
        .slice(0, 30)
        .sort((left, right) => left.reportedTime - right.reportedTime)
    : [];
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
      <section className="day-insights">
        <h2>Whole operational day</h2>
        {loadingVehicleDay && (
          <p className="muted">Loading reports beyond the map filters…</p>
        )}
        {vehicleDayError && <div className="error">{vehicleDayError}</div>}
        {vehicleDay && (
          <>
            <p className="day-scope">
              {vehicleDay.observations.toLocaleString()} reports from{" "}
              {clock(vehicleDay.firstReport)} to {clock(vehicleDay.lastReport)}{" "}
              · {vehicleDay.areas.length} geohash areas. This view ignores the
              current map area, time, and line filters.
            </p>
            <div className="day-metrics">
              <div>
                <strong>{vehicleDay.lines.length}</strong>
                <span>resolved lines</span>
              </div>
              <div>
                <strong>{vehicleDay.gaps.length}</strong>
                <span>report gaps &gt; 2 min</span>
              </div>
              <div>
                <strong>{vehicleDay.stopReports.length}</strong>
                <span>matched stop reports</span>
              </div>
            </div>

            <h2>Lines served</h2>
            {vehicleDay.lines.length ? (
              <div className="day-lines">
                {vehicleDay.lines.map((line) => (
                  <article key={line.line}>
                    <strong>{line.line}</strong>
                    <span>
                      {clock(line.firstReport)}–{clock(line.lastReport)}
                    </span>
                    <small>
                      {line.trips.length} trips · {line.observations} reports
                    </small>
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted">
                None of this vehicle’s trip IDs resolved to a planned line.
              </p>
            )}
            {!!vehicleDay.unresolvedObservations && (
              <p className="coverage-warning">
                {vehicleDay.unresolvedObservations.toLocaleString()} reports had
                no date-valid trip-to-line match, so the line history may be
                incomplete.
              </p>
            )}

            <details className="insight-group" open>
              <summary>Line and trip timeline</summary>
              <div className="insight-list">
                {vehicleDay.linePeriods.map((period, index) => (
                  <article key={`${period.start}-${index}`}>
                    <div>
                      <strong>{period.line ?? "Unresolved line"}</strong>
                      <span>
                        {clock(period.start)}–{clock(period.end)}
                      </span>
                    </div>
                    <small>
                      {period.tripId ? `Trip ${period.tripId}` : "No trip ID"} ·{" "}
                      {period.startArea}
                      {period.endArea !== period.startArea
                        ? ` → ${period.endArea}`
                        : ""}
                    </small>
                  </article>
                ))}
              </div>
            </details>

            <details className="insight-group">
              <summary>Longest report gaps ({vehicleDay.gaps.length})</summary>
              <p className="insight-note">
                A gap means the dataset received no report. It does not by
                itself prove the bus was idle or off route.
              </p>
              <div className="insight-list">
                {importantGaps.map((gap) => (
                  <article key={`${gap.start}-${gap.end}`}>
                    <div>
                      <strong>{formatDuration(gap.durationSeconds)}</strong>
                      <span>
                        {clock(gap.start)}–{clock(gap.end)}
                      </span>
                    </div>
                    <small>
                      {gap.fromArea} → {gap.toArea}
                      {gap.areaChanged ? " · reappeared in another area" : ""}
                      {gap.lineChanged
                        ? ` · line ${gap.fromLine ?? "?"} → ${gap.toLine ?? "?"}`
                        : ""}
                    </small>
                  </article>
                ))}
                {!vehicleDay.gaps.length && (
                  <p className="muted">
                    No report gaps longer than two minutes.
                  </p>
                )}
              </div>
              {vehicleDay.gaps.length > importantGaps.length && (
                <p className="insight-note">Showing the 20 longest gaps.</p>
              )}
            </details>

            <details className="insight-group">
              <summary>
                Schedule-matched stops ({vehicleDay.stopReports.length})
              </summary>
              <p className="insight-note">
                These are feed report times carrying a matching stop ID, not
                independently measured arrivals. Showing up to 30 reports
                nearest the selected report.
              </p>
              <div className="insight-list stop-reports">
                {nearbyStops.map((stop) => (
                  <article
                    key={`${stop.tripId}-${stop.stopSequence}-${stop.reportedTime}`}
                  >
                    <div>
                      <strong>{stop.stopName ?? stop.stopId}</strong>
                      <span>{clock(stop.reportedTime)}</span>
                    </div>
                    <small>
                      Line {stop.line} · stop {stop.stopSequence} ·{" "}
                      {stop.scheduledTime
                        ? `scheduled ${clock(stop.scheduledTime)} · ${formatDifference(stop.differenceSeconds)}`
                        : "scheduled time unavailable"}
                    </small>
                  </article>
                ))}
                {!nearbyStops.length && (
                  <p className="muted">
                    No reports matched both a scheduled trip and stop.
                  </p>
                )}
              </div>
            </details>
          </>
        )}
      </section>
      <h2>Selected report</h2>
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
