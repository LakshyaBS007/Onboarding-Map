"""
Driver Onboarding Gap Dashboard
--------------------------------
Live-reads data from a Google Sheet (read-only) and visualizes H3ID7 cluster-level
driver onboarding on an OpenStreetMap basemap. Primary goal: surface areas where
driver onboarding is NOT happening, especially clusters that already have darkstores.

The sheet is NEVER modified. Data is pulled via the public CSV export endpoint.
"""

import io
import requests
import pandas as pd
import streamlit as st
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import h3
import branca.colormap as cm

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
SHEET_ID = "1_QLcNVNcn9_G3WGFLSuAFC7A1EqZVnRyixkT4xXCXcU"

# Month columns in the cluster tabs, in chronological order (newest first as in sheet)
MONTH_COLS = ["DA(Jun-26)", "DA(May-26)", "DA(Apr-26)", "DA(Mar-26)", "DA(Feb-26)"]
MONTH_LABELS = {
    "DA(Jun-26)": "Jun 2026",
    "DA(May-26)": "May 2026",
    "DA(Apr-26)": "Apr 2026",
    "DA(Mar-26)": "Mar 2026",
    "DA(Feb-26)": "Feb 2026",
}
TOTAL_COL = "Total(L2M)"

st.set_page_config(page_title="Driver Onboarding Gap Dashboard", layout="wide")


# ----------------------------------------------------------------------------
# DATA LOADING  (live, read-only, cached for 5 min so the app stays responsive)
# ----------------------------------------------------------------------------
def csv_url(tab_name: str) -> str:
    # gviz endpoint returns the named tab as CSV without modifying the sheet
    return (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab_name)}"
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_tab(tab_name: str) -> pd.DataFrame:
    r = requests.get(csv_url(tab_name), timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [str(c).strip() for c in df.columns]
    return df


def to_num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


# ----------------------------------------------------------------------------
# H3 GEOMETRY HELPERS
# ----------------------------------------------------------------------------
def h3_polygon(h3_index: str):
    """Return [[lat, lng], ...] boundary for an H3 cell, or None if invalid."""
    try:
        boundary = h3.cell_to_boundary(str(h3_index).strip())
        return [[lat, lng] for lat, lng in boundary]
    except Exception:
        return None


def h3_center(h3_index: str):
    try:
        lat, lng = h3.cell_to_latlng(str(h3_index).strip())
        return lat, lng
    except Exception:
        return None


# ----------------------------------------------------------------------------
# SIDEBAR FILTERS
# ----------------------------------------------------------------------------
st.sidebar.title("Filters")

with st.spinner("Loading live data from Google Sheet..."):
    try:
        clusters = load_tab("H3ID7_Clusters")
        drivers = load_tab("MapDrivers")
        stations = load_tab("ActiveStations")
        darkstores = load_tab("Darkstores")
    except Exception as e:
        st.error(
            "Could not read the Google Sheet. Make sure link-sharing is set to "
            "'Anyone with the link can view'.\n\n"
            f"Details: {e}"
        )
        st.stop()

if st.sidebar.button("🔄 Refresh data now"):
    st.cache_data.clear()
    st.rerun()

# --- Time mode ---
time_mode = st.sidebar.radio(
    "Time period",
    ["Single month", "Total (last 4 months)", "Compare two months"],
    index=0,
)

if time_mode == "Single month":
    sel_month = st.sidebar.selectbox(
        "Month", MONTH_COLS, format_func=lambda c: MONTH_LABELS[c]
    )
    metric_col = sel_month
    compare_cols = None
elif time_mode == "Total (last 4 months)":
    metric_col = TOTAL_COL
    compare_cols = None
else:  # Compare two months
    c1, c2 = st.sidebar.columns(2)
    month_a = c1.selectbox(
        "Month A", MONTH_COLS, index=0, format_func=lambda c: MONTH_LABELS[c]
    )
    month_b = c2.selectbox(
        "Month B", MONTH_COLS, index=1, format_func=lambda c: MONTH_LABELS[c]
    )
    metric_col = None
    compare_cols = (month_a, month_b)

# --- City filter (derived from point tabs that carry a City column) ---
city_values = set()
for df in (drivers, stations, darkstores):
    for col in df.columns:
        if col.strip().lower() == "city":
            city_values.update(df[col].dropna().astype(str).str.strip().unique())
city_options = ["All cities"] + sorted(c for c in city_values if c)
sel_city = st.sidebar.selectbox("City", city_options)

# --- Vehicle type filter (drivers) ---
veh_col = next((c for c in drivers.columns if c.strip().lower() == "vehicletype"), None)
if veh_col:
    veh_opts = ["All"] + sorted(
        drivers[veh_col].dropna().astype(str).str.strip().unique()
    )
    sel_veh = st.sidebar.selectbox("Driver vehicle type", veh_opts)
else:
    sel_veh = "All"

st.sidebar.markdown("---")
st.sidebar.subheader("Map layers")
show_drivers = st.sidebar.checkbox("Onboarded drivers", value=False)
show_stations = st.sidebar.checkbox("Active battery stations", value=True)
show_darkstores = st.sidebar.checkbox("Darkstores", value=True)
gap_only = st.sidebar.checkbox(
    "Only show GAP clusters (darkstores present, 0 onboardings)", value=False
)


# ----------------------------------------------------------------------------
# PREP CLUSTER DATA
# ----------------------------------------------------------------------------
clusters = clusters.copy()
id_col = clusters.columns[0]  # ClusterId
clusters[id_col] = clusters[id_col].astype(str).str.strip()
for c in MONTH_COLS + [TOTAL_COL, "Darkstores"]:
    if c in clusters.columns:
        clusters[c] = to_num(clusters[c])

# Compute the metric used for coloring
if compare_cols:
    a, b = compare_cols
    clusters["metric"] = clusters[a] - clusters[b]  # change A relative to B
    metric_label = f"{MONTH_LABELS[a]} − {MONTH_LABELS[b]} (change)"
else:
    clusters["metric"] = clusters[metric_col]
    metric_label = (
        "Total last 4 months"
        if metric_col == TOTAL_COL
        else MONTH_LABELS.get(metric_col, metric_col)
    )

has_dark = clusters["Darkstores"] > 0 if "Darkstores" in clusters.columns else False
is_gap = (clusters["metric"] <= 0) & has_dark if not compare_cols else (
    (clusters[compare_cols[0]] == 0) & has_dark
)
clusters["is_gap"] = is_gap

view = clusters[clusters["is_gap"]] if gap_only else clusters


# ----------------------------------------------------------------------------
# POINT-LAYER CITY / VEHICLE FILTERING
# ----------------------------------------------------------------------------
def filter_city(df):
    if sel_city == "All cities":
        return df
    ccol = next((c for c in df.columns if c.strip().lower() == "city"), None)
    if not ccol:
        return df
    return df[df[ccol].astype(str).str.strip() == sel_city]


def get_latlng_cols(df):
    lat = next((c for c in df.columns if c.strip().lower() == "latitude"), None)
    lng = next((c for c in df.columns if c.strip().lower() == "longitude"), None)
    return lat, lng


drivers_f = filter_city(drivers)
if veh_col and sel_veh != "All":
    drivers_f = drivers_f[drivers_f[veh_col].astype(str).str.strip() == sel_veh]
stations_f = filter_city(stations)
darkstores_f = filter_city(darkstores)


# ----------------------------------------------------------------------------
# HEADER + KPIs
# ----------------------------------------------------------------------------
st.title("🛵 Driver Onboarding Gap Dashboard")
st.caption(
    f"Live from Google Sheets · H3ID7 clusters · Metric shown: **{metric_label}**"
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Clusters", f"{len(clusters):,}")
k2.metric(
    "Total onboardings (period)",
    f"{int(clusters['metric'].clip(lower=0).sum()):,}" if not compare_cols else "—",
)
gap_count = int(clusters["is_gap"].sum())
k3.metric("⚠️ Gap clusters (darkstore, 0 onboarding)", f"{gap_count:,}")
k4.metric("Darkstores in gap clusters",
          f"{int(clusters.loc[clusters['is_gap'],'Darkstores'].sum()):,}"
          if 'Darkstores' in clusters.columns else "—")


# ----------------------------------------------------------------------------
# BUILD MAP
# ----------------------------------------------------------------------------
# Center map on mean of valid cluster centers
centers = [h3_center(h) for h in clusters[id_col]]
centers = [c for c in centers if c]
map_center = (
    [sum(x[0] for x in centers) / len(centers), sum(x[1] for x in centers) / len(centers)]
    if centers
    else [26.85, 80.95]
)

m = folium.Map(location=map_center, zoom_start=11, tiles="OpenStreetMap")

# Color scale
if compare_cols:
    vmax = max(1, float(view["metric"].abs().max()))
    colormap = cm.LinearColormap(
        ["#b2182b", "#f7f7f7", "#1a9850"], vmin=-vmax, vmax=vmax,
        caption=metric_label,
    )
else:
    vmax = max(1, float(view["metric"].max()))
    colormap = cm.LinearColormap(
        ["#d73027", "#fee08b", "#1a9850"], vmin=0, vmax=vmax,
        caption=f"Onboardings · {metric_label}",
    )
colormap.add_to(m)

hex_group = folium.FeatureGroup(name="H3ID7 clusters", show=True)
for _, row in view.iterrows():
    poly = h3_polygon(row[id_col])
    if not poly:
        continue
    val = row["metric"]
    gap = bool(row["is_gap"])
    fill = colormap(val)
    tooltip = (
        f"<b>Cluster:</b> {row[id_col]}<br>"
        f"<b>{metric_label}:</b> {val:g}<br>"
        f"<b>Darkstores:</b> {int(row.get('Darkstores',0))}<br>"
        f"<b>Total L4M:</b> {int(row.get(TOTAL_COL,0))}"
    )
    folium.Polygon(
        locations=poly,
        color="#7f0000" if gap else "#444444",
        weight=3 if gap else 1,
        fill=True,
        fill_color=fill,
        fill_opacity=0.55,
        tooltip=folium.Tooltip(tooltip),
    ).add_to(hex_group)
hex_group.add_to(m)

# Point layers
if show_darkstores:
    lat_c, lng_c = get_latlng_cols(darkstores_f)
    if lat_c and lng_c:
        grp = folium.FeatureGroup(name="Darkstores", show=True)
        store_col = next((c for c in darkstores_f.columns
                          if c.strip().lower() == "store"), None)
        for _, r in darkstores_f.iterrows():
            try:
                lat, lng = float(r[lat_c]), float(r[lng_c])
            except (ValueError, TypeError):
                continue
            folium.CircleMarker(
                [lat, lng], radius=4, color="#6a1b9a", fill=True,
                fill_color="#9c27b0", fill_opacity=0.9,
                tooltip=str(r[store_col]) if store_col else "Darkstore",
            ).add_to(grp)
        grp.add_to(m)

if show_stations:
    lat_c, lng_c = get_latlng_cols(stations_f)
    if lat_c and lng_c:
        grp = folium.FeatureGroup(name="Active stations", show=True)
        sid = next((c for c in stations_f.columns
                    if c.strip().lower() == "stationid"), None)
        for _, r in stations_f.iterrows():
            try:
                lat, lng = float(r[lat_c]), float(r[lng_c])
            except (ValueError, TypeError):
                continue
            folium.CircleMarker(
                [lat, lng], radius=4, color="#1565c0", fill=True,
                fill_color="#42a5f5", fill_opacity=0.9,
                tooltip=str(r[sid]) if sid else "Station",
            ).add_to(grp)
        grp.add_to(m)

if show_drivers:
    lat_c, lng_c = get_latlng_cols(drivers_f)
    if lat_c and lng_c:
        grp = folium.FeatureGroup(name="Onboarded drivers", show=True)
        mc = MarkerCluster().add_to(grp)
        did = next((c for c in drivers_f.columns
                    if c.strip().lower() == "driverid"), None)
        for _, r in drivers_f.iterrows():
            try:
                lat, lng = float(r[lat_c]), float(r[lng_c])
            except (ValueError, TypeError):
                continue
            folium.CircleMarker(
                [lat, lng], radius=3, color="#2e7d32", fill=True,
                fill_color="#66bb6a", fill_opacity=0.9,
                tooltip=str(r[did]) if did else "Driver",
            ).add_to(mc)
        grp.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, use_container_width=True, height=620, returned_objects=[])


# ----------------------------------------------------------------------------
# GAP TABLE
# ----------------------------------------------------------------------------
st.subheader("⚠️ Onboarding gap clusters")
st.caption(
    "Clusters that already have darkstores but recorded zero onboarding in the "
    "selected period — the priority list for outreach."
)
gap_df = clusters[clusters["is_gap"]].copy()
show_cols = [id_col] + [c for c in MONTH_COLS if c in gap_df.columns] + \
            [TOTAL_COL, "Darkstores"]
gap_df = gap_df[[c for c in show_cols if c in gap_df.columns]] \
    .sort_values("Darkstores", ascending=False)
st.dataframe(gap_df, use_container_width=True, hide_index=True)

st.download_button(
    "Download gap list (CSV)",
    gap_df.to_csv(index=False).encode(),
    file_name="onboarding_gap_clusters.csv",
    mime="text/csv",
)
