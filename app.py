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

# ==========================================
# 1. إعدادات الصفحة
# ==========================================
st.set_page_config(
    layout="wide",
    page_title="نظام إدارة مناطق الفيندورز",
    page_icon="📍"
)

# ==========================================
# 2. دوال المعالجة
# ==========================================
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    s = polygon_str.strip()
    s = re.sub(r'polygon\(\(\s*,\s*', 'polygon((', s, flags=re.IGNORECASE) s = re.sub(r',\s*\)\)', '))', s)
    return s

@st.cache_data
def load_data():
    file_path = 'Dataaa.xlsx'
    
    # تحميل الفيندورز
    df_v = pd.read_excel(file_path, sheet_name='Vendor Location')
    coords = df_v['Vendor Attributes Vendor Map Location'].str.split(',', expand=True)
    df_v['lat'] = pd.to_numeric(coords[0], errors='coerce')
    df_v['lng'] = pd.to_numeric(coords[1], errors='coerce')
    df_v = df_v.dropna(subset=['lat', 'lng'])
    
    df_v['Vendor Attributes Vendor Id'] = df_v['Vendor Attributes Vendor Id'].astype(str)
    df_v['Chain Attributes Chain ID'] = df_v['Chain Attributes Chain ID'].astype(str)

    # تحميل المناطق
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
                
    gdf_a = gpd.GeoDataFrame(
        df_a.loc[valid_indices],
        geometry=geometries,
        crs="EPSG:4326"
    )
    
    # حساب المساحة لاستبعاد المضلعات العملاقة
    gdf_a['area_size'] = gdf_a['geometry'].area
    gdf_a = gdf_a[gdf_a['area_size'] < 0.5]
    gdf_a = gdf_a.sort_values(by='area_size', ascending=False)
    
    # تسريع الرسم
    gdf_a['geometry'] = gdf_a['geometry'].simplify(
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
        request_data.to_csv(file_name, mode='a', header=False, index=False)
    else:
        request_data.to_csv(file_name, index=False)

# ==========================================
# 3. التبويبات
# ==========================================
tab1, tab2, tab3 = st.tabs([
    "🗺️ لوحة المراقبة (الإدارة)",
    "🛒 بوابة الفيندور",
    "📥 طلبات التعديل (الإدارة)"
])

# التبويب الأول
with tab1:
    st.header("لوحة محاكاة المناطق العامة")
    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.write("**أدوات الفلترة**")
        
        # 1. فلتر المدينة
        all_cities = ["الكل"] + sorted(df_vendors['Vendor Attributes Vendor City'].dropna().unique().tolist())
        selected_city = st.selectbox("1. اختر المدينة:", all_cities, key="dash_city")
        
        st.write("---")
        st.write("**بحث متقدم عن الفيندورز:**")
        
        temp_df = df_vendors if selected_city == "الكل" else df_vendors[df_vendors['Vendor Attributes Vendor City'] == selected_city]
        
        # 2. فلتر اسم الفيندور
        vendor_names = ["الكل"] + sorted(temp_df['Vendor Attributes Vendor Name (English)'].dropna().unique().tolist())
        selected_name = st.selectbox("ابحث بـ اسم الفيندور:", vendor_names, key="
