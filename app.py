import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import re
import os
from datetime import datetime
import json

# 1. Page Configuration
st.set_page_config(layout="wide", page_title="Vendor & Zones Management System", page_icon="📍")

# 2. Helper Functions
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

@st.cache_data
def load_data():
    file_path = "Dataaa.xlsx"
    df_v = pd.read_excel(file_path, sheet_name="Vendor Location")
    coords = df_v["Vendor Attributes Vendor Map Location"].str.split(",", expand=True)
    df_v["lat"] = pd.to_numeric(coords[0], errors="coerce")
    df_v["lng"] = pd.to_numeric(coords[1], errors="coerce")
    df_v = df_v.dropna(subset=["lat", "lng"])
    df_v["Vendor Attributes Vendor Id"] = df_v["Vendor Attributes Vendor Id"].astype(str)
    df_v["Chain Attributes Chain ID"] = df_v["Chain Attributes Chain ID"].astype(str)

    df_a = pd.read_excel(file_path, sheet_name="Area")
    df_a["cleaned_wkt"] = df_a["Delivery Location Area Polygon"].apply(clean_wkt)
    
    geometries, valid_indices = [], []
    for idx, wkt_str in df_a["cleaned_wkt"].items():
        if pd.notnull(wkt_str):
            try:
                geometries.append(wkt.loads(wkt_str))
                valid_indices.append(idx)
            except Exception:
                pass
                
    gdf_a = gpd.GeoDataFrame(df_a.loc[valid_indices], geometry=geometries, crs="EPSG:4326")
    gdf_a["area_size"] = gdf_a["geometry"].area
    gdf_a = gdf_a[gdf_a["area_size"] < 0.5]
    gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
    
    # Simplify geometries to optimize browser rendering
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.001, preserve_topology=True)
    return df_v, gdf_a

df_vendors, gdf_areas = load_data()

# Cache JSON conversion to prevent re-calculating on every click
@st.cache_data
def get_vendor_nearby_geojson(lat, lng):
    v_point = Point(lng, lat)
    # 0.3 degree buffer is roughly ~30 km radius
    nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(0.30))
    portal_areas = gdf_areas[nearby_mask]
    return portal_areas[["Delivery Location Area Name", "geometry"]].to_json(), portal_areas

def save_modification_request(vendor_id, vendor_name, original_zones, new_zones):
    request_data = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Vendor ID": vendor_id,
        "Vendor Name": vendor_name,
        "Original Zones": ", ".join(original_zones),
        "Requested Zones": ", ".join(new_zones),
        "Status": "Pending"
    }])
    file_name = "vendor_requests.csv"
    if os.path.exists(file_name):
        request_data.to_csv(file_name, mode="a", header=False, index=False)
    else:
        request_data.to_csv(file_name, index=False)

tab1, tab2, tab3 = st.tabs(["🗺️ Overview Map (Admin)", "🛒 Vendor Portal", "📥 Change Requests (Admin)"])

# Tab 1: Overview Map
with tab1:
    st.header("Zones & Vendors Simulation Dashboard")
    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.subheader("Filter Controls")
        all_cities = ["All"] + sorted(df_vendors["Vendor Attributes Vendor City"].dropna().unique().tolist())
        selected_city = st.selectbox("1. Select City:", options=all_cities, key="dash_city")
        st.markdown("---")
        st.write("**Vendor Search Options:**")
        
        temp_df = df_vendors if selected_city == "All" else df_vendors[df_vendors["Vendor Attributes Vendor City"] == selected_city]
        vendor_names = ["All"] + sorted(temp_df["Vendor Attributes Vendor Name (English)"].dropna().unique().tolist())
        selected_name = st.selectbox("Search by Vendor Name:", options=vendor_names, key="dash_name")
        vendor_ids = ["All"] + sorted(temp_df["Vendor Attributes Vendor Id"].dropna().unique().tolist())
        selected_v_id = st.selectbox("Search by Vendor ID:", options=vendor_ids, key="dash_vid")
        chain_ids = ["All"] + sorted(temp_df["Chain Attributes Chain ID"].dropna().unique().tolist())
        selected_chain = st.selectbox("Search by Chain ID:", options=chain_ids, key="dash_chain")
        st.markdown("---")
        show_zones = st.checkbox("Show Area Polygons", value=True, key="dash_zones")
        
        # We use a trick to clear state cleanly
        if st.button("Reset Filters", key="reset_btn"):
            st.session_state.clear()
            st.rerun()
            
    with col2:
        filtered_v = df_vendors
        if selected_city != "All":
            filtered_v = filtered_v[filtered_v["Vendor Attributes Vendor City"] == selected_city]
        if selected_name != "All":
            filtered_v = filtered_v[filtered_v["Vendor Attributes Vendor Name (English)"] == selected_name]
        if selected_v_id != "All":
            filtered_v = filtered_v[filtered_v["Vendor Attributes Vendor Id"] == selected_v_id]
        if selected_chain != "All":
            filtered_v = filtered_v[filtered_v["Chain Attributes Chain ID"] == selected_chain]
            
        if not filtered_v.empty:
            center = [filtered_v["lat"].mean(), filtered_v["lng"].mean()]
            if selected_name != "All" or selected_v_id != "All":
                zoom = 15
            elif selected_chain != "All":
                zoom = 12
            else:
                zoom = 11 if selected_city != "All" else 6
        else:
            center = [30.0444, 31.2357]
            zoom = 6
            
        m = folium.Map(location=center, zoom_start=zoom)
        
        if show_zones and not gdf_areas.empty:
            folium.GeoJson(
                gdf_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                name="Delivery Zones",
                style_function=lambda feature: {
                    "fillColor": "#0055ff",
                    "color": "#002266",
                    "weight": 1.2,
                    "fillOpacity": 0.25
                },
                tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Area Name: "]),
                popup=folium.GeoJsonPopup(fields=["Delivery Location Area Name"], aliases=["Area Name: "])
            ).add_to(m)
            
        if not filtered_v.empty:
            cluster = MarkerCluster().add_to(m)
            is_searched = (selected_name != "All" or selected_v_id != "All" or selected_chain != "All")
            icon_color = "green" if is_searched else "red"
            icon_shape = "star" if is_searched else "shopping-cart"
            for _, row in filtered_v.iterrows():
                popup_html = f"<b>{row['Vendor Attributes Vendor Name (English)']}</b><br><b>Vendor ID:</b> {row['Vendor Attributes Vendor Id']}<br><b>Chain ID:</b> {row['Chain Attributes Chain ID']}<br><b>Chain Name:</b> {row['Chain Attributes Chain Name']}<br><b>City:</b> {row['Vendor Attributes Vendor City']}"
                folium.Marker(
                    location=[row['lat'], row['lng']],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=row["Vendor Attributes Vendor Name (English)"],
                    icon=folium.Icon(color=icon_color, icon=icon_shape, prefix="fa")
                ).add_to(cluster)
                
        st_folium(m, width="100%", height=600, key="main_map_admin", returned_objects=[])

# Tab 2: Vendor Self-Service Portal
with tab2:
    st.header("Vendor Portal - Coverage Zones Management")
    st.info("Enter your Vendor ID to view your location and managed coverage areas.")
    vendor_input_id = st.text_input("Enter Vendor ID:")
    
    if vendor_input_id:
        v_id_clean = vendor_input_id.strip()
        vendor_data = df_vendors[df_vendors["Vendor Attributes Vendor Id"] == v_id_clean]
        
        if vendor_data.empty:
            st.error("Invalid Vendor ID. Please verify and try again.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row["Vendor Attributes Vendor Name (English)"]
            v_city = v_row["Vendor Attributes Vendor City"]
            st.success(f"Welcome: **{v_name}** | City: {v_city}")
            
            all_available_areas = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())
            initial_covered = all_available_areas[:3] if len(all_available_areas) >= 3 else all_available_areas
            
            # State Initialization
            if "active_vendor_id" not in st.session_state or st.session_state["active_vendor_id"] != v_id_clean:
                st.session_state["active_vendor_id"] = v_id_clean
                st.session_state["selected_zones"] = list(initial_covered)
                st.session_state["vendor_multiselect"] = list(initial_covered)
                st.session_state["vmap_center"] = [v_row["lat"], v_row["lng"]]
                st.session_state["vmap_zoom"] = 12

            # Use cached GeoJSON to prevent lag
            cached_json_str, portal_areas = get_vendor_nearby_geojson(v_row["lat"], v_row["lng"])

            st.markdown("---")
            st.subheader("📍 Current Location & Service Map")
            st.caption("💡 **Tip:** Click directly on any area on the map to add or remove it from your delivery coverage!")

            col_l1, col_l2 = st.columns(2)
            col_l1.markdown("🟢 **Green Areas:** Currently Covered (Delivering here)")
            col_l2.markdown("🔵 **Blue Areas:** Available (Click to add)")

            # Use saved center/zoom to prevent map jump when clicked
            vmap_center = st.session_state.get("vmap_center", [v_row["lat"], v_row["lng"]])
            vmap_zoom = st.session_state.get("vmap_zoom", 12)
            
            v_map = folium.Map(location=vmap_center, zoom_start=vmap_zoom)

            folium.Marker(
                location=[v_row["lat"], v_row["lng"]],
                popup=f"<b>{v_name}</b><br>Store Location",
                tooltip=v_name,
                icon=folium.Icon(color="green", icon="star")
            ).add_to(v_map)

            current_selected_set = set(st.session_state["selected_zones"])

            def vendor_zone_style(feature):
                name = feature["properties"]["Delivery Location Area Name"]
                if name in current_selected_set:
                    return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.50}
                else:
                    return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.0, "fillOpacity": 0.20}

            folium.GeoJson(
                cached_json_str,
                name="Delivery Zones",
                style_function=vendor_zone_style,
                tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Click to Toggle: "])
            ).add_to(v_map)

            # Limit returned_objects to ONLY object_clicked to prevent random loading
            map_data = st_folium(
                v_map,
                width="100%",
                height=520,
                key=f"vendor_map_{v_id_clean}",
                returned_objects=["last_object_clicked"]
            )

            # Handle Map Clicks without using st.rerun() to stop double-loading
            if map_data and map_data.get("last_object_clicked"):
                click = map_data["last_object_clicked"]
                click_pt = Point(click["lng"], click["lat"])
                
                # Check which polygon the click intersects
                matches = portal_areas[portal_areas.geometry.contains(click_pt)].sort_values(by="area_size", ascending=True)
                
                if not matches.empty:
                    clicked_zone = matches.iloc[0]["Delivery Location Area Name"]
                    
                    if clicked_zone in st.session_state["selected_zones"]:
                        st.session_state["selected_zones"].remove(clicked_zone)
