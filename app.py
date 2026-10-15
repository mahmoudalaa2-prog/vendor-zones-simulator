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

# Page configuration
st.set_page_config(layout="wide", page_title="Vendor & Zones Simulator", page_icon="📍")

# Clean WKT function (Protected single-line execution)
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    cleaned = re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE) return re.sub(r',\s*\)\)', '))', cleaned)

@st.cache_data
def load_data():
    file_path = 'Dataaa.xlsx'
    
    # 1. Load Vendors
    df_v = pd.read_excel(file_path, sheet_name='Vendor Location')
    coords = df_v['Vendor Attributes Vendor Map Location'].str.split(',', expand=True)
    df_v['lat'] = pd.to_numeric(coords[0], errors='coerce')
    df_v['lng'] = pd.to_numeric(coords[1], errors='coerce')
    df_v = df_v.dropna(subset=['lat', 'lng'])
    df_v['Vendor Attributes Vendor Id'] = df_v['Vendor Attributes Vendor Id'].astype(str)
    df_v['Chain Attributes Chain ID'] = df_v['Chain Attributes Chain ID'].astype(str)

    # 2. Load Areas
    df_a = pd.read_excel(file_path, sheet_name='Area')
    df_a['cleaned_wkt'] = df_a['Delivery Location Area Polygon'].apply(clean_wkt)
    
    geometries = []
    valid_indices = []
    for idx, wkt_str in df_a['cleaned_wkt'].items():
        if pd.notnull(wkt_str):
            try:
                geometries.append(wkt.loads(wkt_str))
                valid_indices.append(idx)
            except Exception:
                pass
                
    gdf_a = gpd.GeoDataFrame(df_a.loc[valid_indices], geometry=geometries, crs="EPSG:4326")
    gdf_a['area_size'] = gdf_a['geometry'].area
    gdf_a = gdf_a[gdf_a['area_size'] < 0.5]
    gdf_a = gdf_a.sort_values(by='area_size', ascending=False)
    gdf_a['geometry'] = gdf_a['geometry'].simplify(tolerance=0.001, preserve_topology=True)
    
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
        request_data.to_csv(file_name, mode='a', header=False, index=False)
    else:
        request_data.to_csv(file_name, index=False)

# UI Tabs
tab1, tab2, tab3 = st.tabs(["🗺️ لوحة المراقبة (الإدارة)", "🛒 بوابة الفيندور", "📥 طلبات التعديل (الإدارة)"])

# Tab 1: Dashboard
with tab1:
    st.header("لوحة محاكاة المناطق العامة")
    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.write("**أدوات الفلترة**")
        all_cities = ["الكل"] + sorted(df_vendors['Vendor Attributes Vendor City'].dropna().unique().tolist())
        selected_city = st.selectbox("1. اختر المدينة:", all_cities, key="dash_city")
        
        st.write("---")
        st.write("**بحث متقدم عن الفيندورز:**")
        
        temp_df = df_vendors if selected_city == "الكل" else df_vendors[df_vendors['Vendor Attributes Vendor City'] == selected_city]
        
        vendor_names = ["الكل"] + sorted(temp_df['Vendor Attributes Vendor Name (English)'].dropna().unique().tolist())
        selected_name = st.selectbox("ابحث بـ اسم الفيندور:", vendor_names, key="dash_name")
        
        vendor_ids = ["الكل"] + sorted(temp_df['Vendor Attributes Vendor Id'].dropna().unique().tolist())
        selected_v_id = st.selectbox("ابحث بـ Vendor ID:", vendor_ids, key="dash_vid")
        
        chain_ids = ["الكل"] + sorted(temp_df['Chain Attributes Chain ID'].dropna().unique().tolist())
        selected_chain = st.selectbox("ابحث بـ Chain ID:", chain_ids, key="dash_chain")
        
        st.write("---")
        show_zones = st.checkbox("عرض جميع حدود المناطق", value=True, key="dash_zones")
        
        if st.button("🔄 إعادة ضبط الفلاتر"):
            st.rerun()
            
    with col2:
        filtered_v = df_vendors
        if selected_city != "الكل":
            filtered_v = filtered_v[filtered_v['Vendor Attributes Vendor City'] == selected_city]
        if selected_name != "الكل":
            filtered_v = filtered_v[filtered_v['Vendor Attributes Vendor Name (English)'] == selected_name]
        if selected_v_id != "الكل":
            filtered_v = filtered_v[filtered_v['Vendor Attributes Vendor Id'] == selected_v_id]
        if selected_chain != "الكل":
            filtered_v = filtered_v[filtered_v['Chain Attributes Chain ID'] == selected_chain]
            
        if not filtered_v.empty:
            center = [filtered_v['lat'].mean(), filtered_v['lng'].mean()]
            if selected_name != "الكل" or selected_v_id != "الكل":
                zoom = 15
            elif selected_chain != "الكل":
                zoom = 12
            else:
                zoom = 11 if selected_city != "الكل" else 6
        else:
            center = [30.0444, 31.2357]
            zoom = 6
            
        m = folium.Map(location=center, zoom_start=zoom)
        
        if show_zones and not gdf_areas.empty:
            folium.GeoJson(
                gdf_areas[['Delivery Location Area Name', 'Delivery Location Area Name (Arabic)', 'geometry']].to_json(),
                name="مناطق التغطية",
                style_function=lambda feature: {
                    'fillColor': '#0055ff',
                    'color': 'navy',
