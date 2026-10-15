import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import numpy as np
import re
import os
from datetime import datetime

# ==========================================
# 1. إعدادات الصفحة
# ==========================================
st.set_page_config(layout="wide", page_title="Vendor & Zones Management System", page_icon="📍")

# ==========================================
# 2. دوال المعالجة
# ==========================================
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 # نصف قطر الأرض بالكيلومتر
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

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
    
    # حساب مراكز المناطق لحساب المسافات لاحقاً
    centroids = gdf_a.geometry.centroid
    gdf_a["centroid_lat"] = centroids.y
    gdf_a["centroid_lng"] = centroids.x

    # تبسيط المضلعات لتسريع الخريطة
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.002, preserve_topology=False)
    return df_v, gdf_a

df_vendors, gdf_areas = load_data()

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    v_point = Point(lng, lat)
    radius_deg = radius_km / 111.0
    nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(radius_deg))
    return gdf_areas[nearby_mask].copy()

def save_detailed_request(vendor_id, vendor_name, edited_df):
    # تحويل الجدول لنص مقروء
    details = []
    for _, row in edited_df.iterrows():
        details.append(f"{row['Zone']} (Dist: {row['Distance (km)']}km | Time: {row['Delivery Time']} | Fees: {row['Delivery Fees']})")
    
    request_data = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Vendor ID": vendor_id,
        "Vendor Name": vendor_name,
        "Total Zones Count": len(edited_df),
        "Details & Pricing": " \n ".join(details),
        "Status": "Pending"
    }])
    
    file_name = "vendor_pricing_requests.csv"
    if os.path.exists(file_name):
        request_data.to_csv(file_name, mode="a", header=False, index=False)
    else:
        request_data.to_csv(file_name, index=False)

# ==========================================
# 3. واجهة المستخدم والتطبيقات
# ==========================================
tab1, tab2, tab3 = st.tabs(["🗺️ Overview Map (Admin)", "🛒 Vendor Portal", "📥 Change Requests (Admin)"])

# ----------------- Tab 1: Admin -----------------
with tab1:
    st.header("Zones & Vendors Simulation Dashboard")
    st.info("The Admin Map is hidden temporarily to focus on the Vendor Portal functionality.")

# ----------------- Tab 2: Vendor Portal -----------------
with tab2:
    st.header("Vendor Portal - Coverage & Pricing Management")
    st.info("Enter your Vendor ID to view your store location and configure your delivery zones.")
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

            st.markdown("---")
            st.subheader("📍 Map View Radius")
            map_radius_km = st.slider(
                "Adjust how far you want to see zones around your store:",
                min_value=3, max_value=40, value=10, step=1
            )

            portal_areas = get_nearby_polygons(v_row["lat"], v_row["lng"], map_radius_km)
            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())

            # ================== تهيئة المتغيرات (Session State) ==================
            if "vendor_portal_id" not in st.session_state or st.session_state["vendor_portal_id"] != v_id_clean:
                st.session_state["vendor_portal_id"] = v_id_clean
                initial_covered = portal_areas["Delivery Location Area Name"].head(3).tolist()
                
                # ms_zones: المناطق التي تظهر في مربع البحث (تتغير بالضغط على الخريطة)
                st.session_state["ms_zones"] = list(initial_covered)
                # applied_zones: المناطق التي تلون الخريطة (لا تتغير إلا بضغط Apply)
                st.session_state["applied_zones"] = list(initial_covered)
                
                st.session_state["last_clicked_coord"] = None
                st.session_state["show_pricing_table"] = False

            current_applied = st.session_state["applied_zones"]

            st.markdown("---")
            st.subheader(f"🗺️ Live Coverage Map ({len(current_applied)} Zones Applied)")
            st.caption("💡 **Tip:** Click on any zone to add it to your selection box below. It will NOT change color until you click 'Apply'.")

            col_l1, col_l2 = st.columns(2)
            col_l1.markdown("🟢 **Green Areas:** Applied Zones")
            col_l2.markdown("🔵 **Blue Areas:** Available nearby zones")

            # --- بناء الخريطة بناءً على applied_zones المعتمدة فقط ---
            v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=13)

            folium.Marker(
                location=[v_row["lat"], v_row["lng"]],
                popup=f"<b>{v_name}</b><br>Store Location",
                tooltip=v_name,
                icon=folium.Icon(color="green", icon="star")
            ).add_to(v_map)

            applied_set = set(current_applied)

            def vendor_zone_style(feature):
                name = feature["properties"]["Delivery Location Area Name"]
                if name in applied_set:
                    return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.55}
                else:
                    return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.0, "fillOpacity": 0.15}

            folium.GeoJson(
                portal_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                name="Delivery Zones",
                style_function=vendor_zone_style,
                tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Click to Select: "])
            ).add_to(v_map)

            # تفعيل التقاط النقرات
            map_data = st_folium(v_map, width="100%", height=480, key=f"vendor_map_{v_id_clean}_{map_radius_km}", returned_objects=["last_clicked"])

            # معالجة النقرات (تضاف للصندوق ms_zones ولا تؤثر على الخريطة applied_zones)
            if map_data and map_data.get("last_clicked"):
                click = map_data["last_clicked"]
                if click != st.session_state.get("last_clicked_coord"):
                    st.session_state["last_clicked_coord"] = click
                    click_pt = Point(click["lng"], click["lat"])
                    
                    matches = portal_areas[portal_areas.geometry.contains(click_pt)]
                    if not matches.empty:
                        clicked_zone = matches.iloc[0]["Delivery Location Area Name"]
                        
                        # إضافة أو إزالة من مربع البحث فقط
                        if clicked_zone in st.session_state["ms_zones"]:
                            st.session_state["ms_zones"].remove(clicked_zone)
                        else:
                            st.session_state["ms_zones"].append(clicked_zone)
                            
                        # إغلاق جدول التسعير إذا تم تعديل الاختيارات
                        st.session_state["show_pricing_table"] = False
                        st.rerun()

            st.markdown("---")
            st.subheader("📝 Selected Service Areas")
            
            # صندوق البحث (مرتبط بـ ms_zones)
            chosen_zones = st.multiselect(
                "Click on the map or type to add zones to your list:",
                options=all_available_zones,
                key="ms_zones" # التزامن التلقائي مع الـ Session State
            )

            # أزرار التحكم
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
            with btn_col1:
                if st.button("👁️ Apply to Map", type="secondary", use_container_width=True):
                    # تطبيق الاختيارات على الخريطة
                    st.session_state["applied_zones"] = st.session_state["ms_zones"].copy()
                    st.session_state["show_pricing_table"] = False
                    st.rerun()
                    
            with btn_col2:
                if st.button("🚀 Submit Selection", type="primary", use_container_width=True):
                    if not st.session_state["applied_zones"]:
                        st.warning("Please select and Apply at least one zone first.")
                    else:
                        st.session_state["show_pricing_table"] = True

            # ==========================================
            # 4. جدول تحديد المسافات والأسعار (Data Editor)
            # ==========================================
            if st.session_state.get("show_pricing_table", False):
                st.markdown("---")
                st.subheader("💰 Set Delivery Pricing & Time")
                st.info("Please fill in the estimated delivery time and fees for each selected zone based on the distance.")

                # بناء جدول البيانات للمناطق المعتمدة (applied_zones)
                current_applied_hash = ",".join(sorted(st.session_state["applied_zones"]))
                
                # إذا تغيرت المناطق، نعيد تهيئة الجدول
                if st.session_state.get("pricing_hash") != current_applied_hash:
                    pricing_data = []
                    for zone in st.session_state["applied_zones"]:
                        zone_row = gdf_areas[gdf_areas["Delivery Location Area Name"] == zone]
                        if not zone_row.empty:
                            z_lat = zone_row.iloc[0]["centroid_lat"]
                            z_lng = zone_row.iloc[0]["centroid_lng"]
                            dist = haversine_km(v_row["lat"], v_row["lng"], z_lat, z_lng)
                        else:
                            dist = 0.0
                            
                        pricing_data.append({
                            "Zone": zone,
                            "Distance (km)": round(dist, 1),
                            "Delivery Time": "",   # خانة فارغة للوقت
                            "Delivery Fees": None  # خانة فارغة للسعر
                        })
                    
                    # حفظ الجدول في الـ State ليحتفظ بتعديلات الفيندور
                    st.session_state["pricing_df"] = pd.DataFrame(pricing_data)
                    st.session_state["pricing_hash"] = current_applied_hash

                # عرض الجدول القابل للتعديل
                edited_pricing_df = st.data_editor(
                    st.session_state["pricing_df"],
                    column_config={
                        "Zone": st.column_config.TextColumn("Zone Name", disabled=True),
                        "Distance (km)": st.column_config.NumberColumn("Distance (km)", disabled=True),
                        "Delivery Time": st.column_config.TextColumn("Delivery Time (e.g., 30 mins)", required=True),
                        "Delivery Fees": st.column_config.NumberColumn("Delivery Fees (EGP)", required=True)
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="pricing_editor"
                )

                # زر الحفظ النهائي للإدارة
                if st.button("✅ Finalize & Send to Admin", type="primary"):
                    # التحقق من أن جميع البيانات مكتملة
                    if edited_pricing_df["Delivery Time"].eq("").any() or edited_pricing_df["Delivery Fees"].isnull().any():
                        st.error("⚠️ Please fill in the Delivery Time and Delivery Fees for all zones before saving.")
                    else:
                        save_detailed_request(v_id_clean, v_name, edited_pricing_df)
                        st.success("🎉 Success! Your zones, delivery times, and fees have been submitted to Admin.")

# ----------------- Tab 3: Admin Review -----------------
with tab3:
    st.header("📥 Vendor Pricing & Coverage Requests")
    if os.path.exists("vendor_pricing_requests.csv"):
        req_df = pd.read_csv("vendor_pricing_requests.csv")
        st.dataframe(req_df, use_container_width=True)
        with open("vendor_pricing_requests.csv", "rb") as file:
            st.download_button(label="📥 Download Detailed Requests (CSV)", data=file, file_name="vendor_pricing_updates.csv", mime="text/csv")
    else:
        st.info("No detailed requests received yet.")
