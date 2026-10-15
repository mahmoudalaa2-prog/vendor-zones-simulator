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
st.set_page_config(
    layout="wide",
    page_title="Vendor & Zones Management System",
    page_icon="📍"
)

# 2. Helper Functions
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    cleaned = re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE) cleaned = re.sub(r',\s*\)\)', '))', cleaned)
    return cleaned

@st.cache_data
def load_data():
    file_path = "Dataaa.xlsx"
    
    # Load Vendors
    df_v = pd.read_excel(file_path, sheet_name="Vendor Location")
    coords = df_v["Vendor Attributes Vendor Map Location"].str.split(",", expand=True)
    df_v["lat"] = pd.to_numeric(coords[0], errors="coerce")
    df_v["lng"] = pd.to_numeric(coords[1], errors="coerce")
    df_v = df_v.dropna(subset=["lat", "lng"])
    
    df_v["Vendor Attributes Vendor Id"] = df_v["Vendor Attributes Vendor Id"].astype(str)
    df_v["Chain Attributes Chain ID"] = df_v["Chain Attributes Chain ID"].astype(str)

    # Load Areas
    df_a = pd.read_excel(file_path, sheet_name="Area")
    df_a["cleaned_wkt"] = df_a["Delivery Location Area Polygon"].apply(clean_wkt)
    
    geometries = []
    valid_indices = []
    for idx, wkt_str in df_a["cleaned_wkt"].items():
        if pd.notnull(wkt_str):
            try:
                geometries.append(wkt.loads(wkt_str))
                valid_indices.append(idx)
            except Exception:
                pass
                
    gdf_a = gpd.GeoDataFrame(
        df_a.loc[valid_indices],
        geometry=geometries,
        crs="EPSG:4326"
    )
    
    # Filter out country-wide overlapping polygons
    gdf_a["area_size"] = gdf_a["geometry"].area
    gdf_a = gdf_a[gdf_a["area_size"] < 0.5]
    gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
    
    # Simplify geometries to optimize browser rendering
    gdf_a["geometry"] = gdf_a["geometry"].simplify(
        tolerance=0.001,
        preserve_topology=True
    )
    
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

# 3. Application Tabs
tab1, tab2, tab3 = st.tabs([
    "🗺️ Overview Map (Admin)",
    "🛒 Vendor Portal",
    "📥 Change Requests (Admin)"
])

# Tab 1: Overview Map
with tab1:
    st.header("Zones & Vendors Simulation Dashboard")
    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.subheader("Filter Controls")
        
        # City Filter
        all_cities = ["All"] + sorted(
            df_vendors["Vendor Attributes Vendor City"].dropna().unique().tolist()
        )
        selected_city = st.selectbox(
            "1. Select City:",
            options=all_cities,
            key="dash_city"
        )
        
        st.markdown("---")
        st.write("**Vendor Search Options:**")
        
        temp_df = df_vendors if selected_city == "All" else df_vendors[df_vendors["Vendor Attributes Vendor City"] == selected_city]
        
        # Vendor Name Filter
        vendor_names = ["All"] + sorted(
            temp_df["Vendor Attributes Vendor Name (English)"].dropna().unique().tolist()
        )
        selected_name = st.selectbox(
            "Search by Vendor Name:",
            options=vendor_names,
            key
