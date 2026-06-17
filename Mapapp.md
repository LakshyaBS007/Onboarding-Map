# Driver Onboarding Gap Dashboard

A Streamlit + OpenStreetMap web app that live-reads your Google Sheet and
visualizes H3ID7 cluster-level driver onboarding. Its purpose is to surface
**areas where driver onboarding is not happening** — especially clusters that
already have darkstores but recorded zero onboardings.

The app only **reads** the sheet (via the public CSV export endpoint). It never
writes to or changes your data.

---

## 1. One-time setup on the Google Sheet (read access)

The app reads each tab through Google's CSV export endpoint, which requires the
sheet to be viewable:

1. Open the sheet → **Share** (top right).
2. Under *General access*, set **"Anyone with the link" → Viewer**.
3. Done. No API key, no service account, nothing is written back.

(If your org forbids link-sharing, the alternative is **File → Share → Publish to
web → publish each tab as CSV**, which exposes only those tabs read-only.)

The tab names the app expects (exactly):
`H3ID7_Clusters`, `MapDrivers`, `ActiveStations`, `Darkstores`.

---

## 2. Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

---

## 3. Deploy a shareable link (free)

**Streamlit Community Cloud:**

1. Put `app.py` and `requirements.txt` in a GitHub repo.
2. Go to https://share.streamlit.io → **New app** → pick the repo/branch/`app.py`.
3. Deploy. You get a public `https://<your-app>.streamlit.app` URL to share.

Because the app pulls live from the sheet on each load (cached 5 min), whenever
the sheet updates, the dashboard reflects it — use the **🔄 Refresh data now**
button to force an immediate re-pull.

---

## Features

- **H3ID7 hexagon polygons** color-coded by onboardings (red = none → green = high).
  Hexagon geometry is computed from the H3 index itself, so no lat/long column is
  needed in the cluster tab.
- **Gap highlighting:** clusters with darkstores present but 0 onboardings get a
  bold dark-red outline and appear in a downloadable **gap table**.
- **Time filter:** single month (Jun → Feb 2026), Total last 4 months, or
  **compare two months** (diverging red↔green change map).
- **Toggleable point layers:** onboarded drivers, active battery stations, darkstores.
- **Filters:** City, driver vehicle type, and a "gap clusters only" toggle.
- KPIs for cluster count, period onboardings, and the darkstore-gap counts.

## Notes / assumptions

- "Gap" = darkstores present **and** onboardings ≤ 0 in the selected period (in
  compare mode, gap = month A is 0 with darkstores present). Adjust the `is_gap`
  logic in `app.py` if you want a different threshold (e.g. ≤ 2 instead of 0).
- The cluster color metric uses the H3ID7_Clusters tab columns directly; the
  point layers are filtered by City/vehicle independently.
