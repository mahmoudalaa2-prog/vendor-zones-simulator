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
st.set_page_config(layout="wide", page_title="Vendor & Zones Management", page_icon="📍")

# ==========================================
# 2. دوال المعالجة
# ==========================================
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 # نصف قطر الأرض
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
    
    centroids = gdf_a.geometry.centroid
    gdf_a["centroid_lat"] = centroids.y
    gdf_a["centroid_lng"] = centroids.x
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
    details = []
    for _, row in edited_df.iterrows():
        details.append(f"{row['Zone']} (Dist: {row['Distance (km)']}km | Time: {row['Delivery Time']} | Fees: {row['Delivery Fees']})")
    
    request_data = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Vendor ID": vendor_id,
        "Vendor Name": vendor_name,
        "Total Zones Count": len(edited_df),
        "Details & Pricing": " | ".join(details),
        "Status": "Pending"
    }])
    file_name = "vendor_pricing_requests.csv"
    if os.path.exists(file_name):
        request_data.to_csv(file_name, mode="a", header=False, index=False)
    else:
        request_data.to_csv(file_name, index=False)

tab1, tab2, tab3 = st.tabs(["🗺️ Overview Map (Admin)", "🛒 Vendor Portal", "📥 Change Requests (Admin)"])

# ==========================================
# Tab 1: Admin Map (Simplified)
# ==========================================
with tab1:
    st.header("Zones & Vendors Simulation Dashboard")
    st.info("The Admin Map is active.")

# ==========================================
# Tab 2: Vendor Portal (The Perfect Logic)
# ==========================================
with tab2:
    st.header("Vendor Portal - Coverage & Pricing Management")
    st.info("Enter your Vendor ID to view your store location and configure your delivery zones.")
    vendor_input_id = st.text_input("Enter Vendor ID:")
    
    if vendor_input_id:
        v_id_clean = vendor_input_id.strip()
        vendor_data = df_vendors[df_vendors["Vendor Attributes Vendor Id"] == v_id_clean]
        
        if vendor_data.empty:
            st.error("Invalid Vendor ID.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row["Vendor Attributes Vendor Name (English)"]
            v_city = v_row["Vendor Attributes Vendor City"]
            st.success(f"Welcome: **{v_name}** | City: {v_city}")

            map_radius_km = st.slider("Map View Radius (km):", min_value=3, max_value=40, value=10, step=1)
            portal_areas = get_nearby_polygons(v_row["lat"], v_row["lng"], map_radius_km)
            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())

            # ---------------- تهيئة المتغيرات ----------------
            if "vendor_portal_id" not in st.session_state or st.session_state["vendor_portal_id"] != v_id_clean:
                st.session_state["vendor_portal_id"] = v_id_clean
                initial_covered = portal_areas["Delivery Location Area Name"].head(3).tolist()
                
                # ms_zones: المناطق في مربع البحث (تتحدث مع النقرات)
                st.session_state["ms_zones"] = list(initial_covered)
                # applied_zones: المناطق الملونة على الخريطة (لا تتحدث إلا بضغطة Apply)
                st.session_state["applied_zones"] = list(initial_covered)
                
                st.session_state["last_click_id"] = None
                st.session_state["show_pricing_table"] = False

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])

            # ---------------- رسم الخريطة ----------------
            with col_map:
                st.subheader(f"🗺️ Map ({len(st.session_state['applied_zones'])} Zones Applied)")
                st.caption("Click a zone to automatically add it to the search box on the right without changing colors.")
                
                v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=13)
                folium.Marker(
                    location=[v_row["lat"], v_row["lng"]],
                    popup=f"<b>{v_name}</b>",
                    tooltip="Store Location",
                    icon=folium.Icon(color="green", icon="star")
                ).add_to(v_map)

                applied_set = set(st.session_state["applied_zones"])

                # تلوين المناطق بناءً على applied_zones فقط! 
                # (لذلك النقرة لن تغير اللون، ولن يتم إعادة تحميل الخريطة من الصفر)
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

                # التقاط النقرة
                map_data = st_folium(v_map, width="100%", height=500, key=f"vmap_{v_id_clean}_{map_radius_km}", returned_objects=["last_clicked"])

                # ---------------- معالجة النقرات (بدون Rerun صريح) ----------------
                if map_data and map_data.get("last_clicked"):
                    click = map_data["last_clicked"]
                    click_sig = f"{click['lat']}_{click['lng']}"
                    
                    if click_sig != st.session_state.get("last_click_id"):
                        st.session_state["last_click_id"] = click_sig
                        click_pt = Point(click["lng"], click["lat"])
                        
                        matches = portal_areas[portal_areas.geometry.contains(click_pt)]
                        if matches.empty:
                            dists = portal_areas.geometry.distance(click_pt)
                            if not dists.empty and dists.min() < 0.005:
                                matches = portal_areas.loc[[dists.idxmin()]]
                                
                        if not matches.empty:
                            clicked_zone_name = matches.iloc[0]["Delivery Location Area Name"]
                            
                            # إضافة أو إزالة المنطقة من مربع البحث فقط
                            if clicked_zone_name in st.session_state["ms_zones"]:
                                st.session_state["ms_zones"].remove(clicked_zone_name)
                            else:
                                st.session_state["ms_zones"].append(clicked_zone_name)
                            
                            st.session_state["show_pricing_table"] = False
                            # الملاحظة هنا: بمجرد تحديث ms_zones، سيتم تحديث مربع البحث في الأسفل تلقائياً 
                            # لأن Streamlit تقوم بتحديث المتغيرات من الأعلى للأسفل، ولا نحتاج لـ st.rerun المزعج!

            # ---------------- صندوق البحث والأزرار ----------------
            with col_form:
                st.subheader("📝 Selected Zones")
                st.caption("Zones you click on the map will instantly appear here.")

                # مزامنة بيانات مربع البحث مع النقرات
                st.session_state["ms_zones_widget"] = st.session_state["ms_zones"]

                def sync_ms_zones():
                    st.session_state["ms_zones"] = st.session_state["ms_zones_widget"]

                chosen_zones = st.multiselect(
                    "Service Areas:",
                    options=all_available_zones,
                    key="ms_zones_widget",
                    on_change=sync_ms_zones
                )

                btn_col1, btn_col2 = st.columns([1, 1])
                
                with btn_col1:
                    # زر Apply يطبق الألوان على الخريطة
                    if st.button("👁️ Apply to Map", type="secondary", use_container_width=True):
                        st.session_state["applied_zones"] = st.session_state["ms_zones"].copy()
                        st.session_state["show_pricing_table"] = False
                        st.rerun()
                        
                with btn_col2:
                    # زر Submit يفتح جدول التسعير
                    if st.button("🚀 Submit Selection", type="primary", use_container_width=True):
                        if not st.session_state["applied_zones"]:
                            st.warning("Please select and 'Apply to Map' at least one zone first.")
                        elif set(st.session_state["applied_zones"]) != set(st.session_state["ms_zones"]):
                            st.warning("You have unapplied changes! Please click 'Apply to Map' first.")
                        else:
                            st.session_state["show_pricing_table"] = True
                            st.rerun()

            # ==========================================
            # 4. جدول تحديد المسافات والأسعار (DataGrid)
            # ==========================================
            if st.session_state.get("show_pricing_table", False):
                st.markdown("---")
                st.subheader("💰 Set Delivery Pricing & Time")
                st.info("Please fill in the estimated delivery time and fees for each selected zone based on the distance.")

                current_applied_hash = ",".join(sorted(st.session_state["applied_zones"]))
                
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
                            "Delivery Time": "",
                            "Delivery Fees": None
                        })
                    
                    st.session_state["pricing_df"] = pd.DataFrame(pricing_data)
                    st.session_state["pricing_hash"] = current_applied_hash

                edited_pricing_df = st.data_editor(
                    st.session_state["pricing_df"],
                    column_config={
                        "Zone": st.column_config.TextColumn("Zone Name", disabled=True),
                        "Distance (km)": st.column_config.NumberColumn("Distance (km)", disabled=True),
                        "Delivery Time": st.column_config.TextColumn("Delivery Time (e.g., 45 mins)", required=True),
                        "Delivery Fees": st.column_config.NumberColumn("Delivery Fees (EGP)", required=True)
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="pricing_editor"
                )

                if st.button("✅ Finalize & Send to Admin", type="primary"):
                    if edited_pricing_df["Delivery Time"].eq("").any() or edited_pricing_df["Delivery Fees"].isnull().any():
                        st.error("⚠️ Please fill in the Delivery Time and Delivery Fees for all zones before saving.")
                    else:
                        save_detailed_request(v_id_clean, v_name, edited_pricing_df)
                        st.success("🎉 Success! Your zones, delivery times, and fees have been submitted to Admin.")

# ==========================================
# Tab 3: Admin Review
# ==========================================
with tab3:
    st.header("📥 Vendor Pricing & Coverage Requests")
    if os.path.exists("vendor_pricing_requests.csv"):
        req_df = pd.read_csv("vendor_pricing_requests.csv")
        st.dataframe(req_df, use_container_width=True)
        with open("vendor_pricing_requests.csv", "rb") as file:
            st.download_button("📥 Download (CSV)", file, "vendor_pricing.csv", "text/csv")
    else:
        st.info("No detailed requests received yet.")
