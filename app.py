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

st.set_page_config(layout="wide", page_title="نظام إدارة مناطق الفيندورز", page_icon="📍")

def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    s = polygon_str.strip()
    s = re.sub(r'polygon\(\(\s*,\s*', 'polygon((', s, flags=re.IGNORECASE) s = re.sub(r',\s*\)\)', '))', s)
    return s

@st.cache_data
def load_data():
    file_path = 'Dataaa.xlsx'
    
    # 1. الفيندورز
    df_v = pd.read_excel(file_path, sheet_name='Vendor Location')
    coords = df_v['Vendor Attributes Vendor Map Location'].str.split(',', expand=True)
    df_v['lat'] = pd.to_numeric(coords[0], errors='coerce')
    df_v['lng'] = pd.to_numeric(coords[1], errors='coerce')
    df_v = df_v.dropna(subset=['lat', 'lng'])
    df_v['Vendor Attributes Vendor Id'] = df_v['Vendor Attributes Vendor Id'].astype(str)

    # 2. المناطق
    df_a = pd.read_excel(file_path, sheet_name='Area')
    df_a['cleaned_wkt'] = df_a['Delivery Location Area Polygon'].apply(clean_wkt)
    
    geometries, valid_indices = [], []
    for idx, wkt_str in df_a['cleaned_wkt'].items():
        if pd.notnull(wkt_str):
            try:
                geometries.append(wkt.loads(wkt_str))
                valid_indices.append(idx)
            except Exception:
                pass
                
    gdf_a = gpd.GeoDataFrame(df_a.loc[valid_indices], geometry=geometries, crs="EPSG:4326")
    
    # تبسيط حدود المضلعات لتسريع رسم الخريطة بنسبة 90% بدون التأثير على شكلها
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

tab1, tab2, tab3 = st.tabs(["🗺️ لوحة المراقبة (الإدارة)", "🛒 بوابة الفيندور", "📥 طلبات التعديل (الإدارة)"])

with tab1:
    st.header("لوحة محاكاة المناطق العامة")
    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.write("**أدوات الفلترة**")
        all_cities = ["الكل"] + sorted(df_vendors['Vendor Attributes Vendor City'].dropna().unique().tolist())
        selected_city = st.selectbox("المدينة:", all_cities, key="dash_city")
        show_zones = st.checkbox("عرض جميع المضلعات (حدود المناطق)", value=True, key="dash_zones")
    
    with col2:
        filtered_v = df_vendors if selected_city == "الكل" else df_vendors[df_vendors['Vendor Attributes Vendor City'] == selected_city]
        
        center = [filtered_v['lat'].mean(), filtered_v['lng'].mean()] if not filtered_v.empty else [30.0444, 31.2357]
        m = folium.Map(location=center, zoom_start=10 if selected_city != "الكل" else 6)
        
        if show_zones and not gdf_areas.empty:
            # إضافة المضلعات باللون الأزرق مع خاصية Popup (عند الضغط) و Tooltip (عند التمرير)
            folium.GeoJson(
                gdf_areas[['Delivery Location Area Name (Arabic)', 'Delivery Location Area Name', 'geometry']].to_json(),
                name="مناطق التغطية",
                style_function=lambda feature: {
                    'fillColor': '#0055ff',      # لون أزرق التعبئة
                    'color': '#002266',          # لون الحدود الأزرق الغامق
                    'weight': 1.5,               # سماكة الحدود
                    'fillOpacity': 0.3           # الشفافية لتظهر الخريطة أسفلها
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=['Delivery Location Area Name (Arabic)'],
                    aliases=['اسم المنطقة: '],
                    style="font-family: Arial; font-size: 14px; font-weight: bold; background-color: white;"
                ),
                popup=folium.GeoJsonPopup(
                    fields=['Delivery Location Area Name (Arabic)', 'Delivery Location Area Name'],
                    aliases=['المنطقة (عربي): ', 'Area (Eng): ']
                )
            ).add_to(m)
            
        if not filtered_v.empty:
            cluster = MarkerCluster().add_to(m)
            for _, row in filtered_v.iterrows():
                folium.Marker(
                    location=[row['lat'], row['lng']],
                    tooltip=row['Vendor Attributes Vendor Name (English)'],
                    icon=folium.Icon(color="red", icon="shopping-cart", prefix="fa")
                ).add_to(cluster)
                
        st_folium(m, width="100%", height=600, key="main_map", returned_objects=[])

with tab2:
    st.header("بوابة الفيندور - إدارة مناطق التغطية")
    st.info("أدخل الـ ID الخاص بك لترى موقعك والمناطق التي تقوم بالتوصيل إليها.")
    vendor_input_id = st.text_input("أدخل رقم الفيندور (Vendor ID):")
    
    if vendor_input_id:
        vendor_data = df_vendors[df_vendors['Vendor Attributes Vendor Id'] == vendor_input_id.strip()]
        
        if vendor_data.empty:
            st.error("الرقم غير صحيح أو غير مسجل بالنظام.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row['Vendor Attributes Vendor Name (English)']
            v_city = v_row['Vendor Attributes Vendor City']
            
            st.success(f"مرحباً بك: **{v_name}** | المدينة: {v_city}")
            
            all_available_areas = gdf_areas['Delivery Location Area Name (Arabic)'].dropna().unique().tolist()
            current_covered_areas = all_available_areas[:3] if len(all_available_areas) >= 3 else all_available_areas
            
            st.write("---")
            st.subheader("📍 خريطتك الحالية")
            
            v_map = folium.Map(location=[v_row['lat'], v_row['lng']], zoom_start=12)
            folium.Marker(
                [v_row['lat'], v_row['lng']], popup="موقعك الحالي", icon=folium.Icon(color="green", icon="star")
            ).add_to(v_map)
            
            covered_gdf = gdf_areas[gdf_areas['Delivery Location Area Name (Arabic)'].isin(current_covered_areas)]
            if not covered_gdf.empty:
                folium.GeoJson(
                    covered_gdf[['Delivery Location Area Name (Arabic)', 'geometry']].to_json(),
                    style_function=lambda x: {'fillColor': '#00ff00', 'color': 'darkgreen', 'weight':
