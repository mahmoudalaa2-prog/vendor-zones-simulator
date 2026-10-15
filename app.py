import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely import wkt
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import re
import os
from datetime import datetime

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
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.001, preserve_topology=True)
    return df_v, gdf_a

df_vendors, gdf_areas = load_data()

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
        if st.button("Reset Filters", key="reset_btn"):
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
                
        st_folium(m, width="100%", height=600, key="main_map", returned_objects=[])

with tab2:
    st.header("Vendor Portal - Coverage Zones Management")
    st.info("Enter your Vendor ID to view your location and managed coverage areas.")
    vendor_input_id = st.text_input("Enter Vendor ID:")
    
    if vendor_input_id:
        vendor_data = df_vendors[df_vendors["Vendor Attributes Vendor Id"] == vendor_input_id.strip()]
        if vendor_data.empty:
            st.error("Invalid Vendor ID. Please verify and try again.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row["Vendor Attributes Vendor Name (English)"]
            v_city = v_row["Vendor Attributes Vendor City"]
            st.success(f"Welcome: **{v_name}** | City: {v_city}")
            all_available_areas = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())
            current_covered_areas = all_available_areas[:3] if len(all_available_areas) >= 3 else all_available_areas
            
            st.markdown("---")
            st.subheader("📍 Current Location & Service Map")
            v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=12)
            folium.Marker(location=[v_row["lat"], v_row["lng"]], popup="Your Store Location", icon=folium.Icon(color="green", icon="star")).add_to(v_map)
            
            covered_gdf = gdf_areas[gdf_areas["Delivery Location Area Name"].isin(current_covered_areas)]
            if not covered_gdf.empty:
                folium.GeoJson(
                    covered_gdf[["Delivery Location Area Name", "geometry"]].to_json(),
                    style_function=lambda x: {"fillColor": "#00ff00", "color": "darkgreen", "weight": 2, "fillOpacity": 0.4},
                    tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Covered Zone: "])
                ).add_to(v_map)
                
            st_folium(v_map, width="100%", height=400, key=f"map_{vendor_input_id}", returned_objects=[])
            
            st.markdown("---")
            st.subheader("📝 Request Zone Coverage Updates")
            with st.form("vendor_update_form"):
                st.write("Add or remove delivery areas you service:")
                updated_zones = st.multiselect("Service Areas:", options=all_available_areas, default=current_covered_areas)
                submit_btn = st.form_submit_button("Submit Modification Request")
                if submit_btn:
                    if set(updated_zones) == set(current_covered_areas):
                        st.warning("No changes detected in your zone selection.")
                    else:
                        save_modification_request(vendor_input_id, v_name, current_covered_areas, updated_zones)
                        st.success("✅ Modification request submitted successfully! Pending admin review.")

with tab3:
    st.header("📥 Vendor Coverage Change Requests")
    if os.path.exists("vendor_requests.csv"):
        req_df = pd.read_csv("vendor_requests.csv")
        st.dataframe(req_df, use_container_width=True)
        with open("vendor_requests.csv", "rb") as file:
            st.download_button(label="📥 Download Requests Log (CSV)", data=file, file_name="vendor_coverage_updates.csv", mime="text/csv")
    else:
        st.info("No modification requests received yet.")
