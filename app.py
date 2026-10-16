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
# 2. دوال المعالجة والمسافات
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
    
    # -------------------------------------------------------------
    # استبعاد فقط ما يبدأ بـ MCD أو McDonald's ومضلعات الجمهورية العامة (> 0.5)
    # مع الإبقاء على كافة الكمبوندات، النوادي، والجامعات والأحياء السكنية كاملة
    # -------------------------------------------------------------
    mask_mcd = gdf_a["Delivery Location Area Name"].str.contains(r"^mcd|^mcdonald", case=False, na=False)
    gdf_a = gdf_a[(~mask_mcd) & (gdf_a["area_size"] < 0.5)].copy()
    
    # الترتيب تنازلي (الأكبر أولاً) حتى تُرسم المناطق الكبيرة في الخلفية والصغيرة في الأعلى
    gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
    
    centroids = gdf_a.geometry.centroid
    gdf_a["centroid_lat"] = centroids.y
    gdf_a["centroid_lng"] = centroids.x
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.0005, preserve_topology=True)
    return df_v, gdf_a

df_vendors, gdf_areas = load_data()

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    v_point = Point(lng, lat)
    radius_deg = radius_km / 111.0
    nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(radius_deg))
    return gdf_areas[nearby_mask].copy()

def save_detailed_request(vendor_id, vendor_name, edited_df):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_df = edited_df.copy()
    save_df.insert(0, "Date", date_str)
    save_df.insert(1, "Vendor ID", str(vendor_id))
    save_df.insert(2, "Vendor Name", vendor_name)
    save_df["Status"] = "Pending"
    
    file_name = "vendor_pricing_requests.csv"
    if os.path.exists(file_name):
        old_df = pd.read_csv(file_name)
        if "Zone" not in old_df.columns:
            save_df.to_csv(file_name, index=False)
        else:
            save_df.to_csv(file_name, mode="a", header=False, index=False)
    else:
        save_df.to_csv(file_name, index=False)

tab1, tab2, tab3 = st.tabs(["🗺️ Overview Map (Admin)", "🛒 Vendor Portal", "📥 Change Requests (Admin)"])

# ==========================================
# Tab 1: Admin Map (لوحة المراقبة مع زر التفعيل/التعطيل)
# ==========================================
with tab1:
    st.header("Zones & Vendors Simulation Dashboard")
    map_active = st.toggle("⚡ Activate Admin Map (تشغيل الخريطة الكبيرة)", value=False, key="toggle_admin_map")
    
    if not map_active:
        st.info("⏸️ **خريطة المراقبة الكبيرة معطلة لتسريع الموقع بنسبة 100%.** فَعِّل الزر بالأعلى عندما تحتاج لمراجعة الخريطة العامة.")
    else:
        col1, col2 = st.columns([1, 4])
        with col1:
            st.subheader("Filter Controls")
            all_cities = ["All"] + sorted(df_vendors["Vendor Attributes Vendor City"].dropna().unique().tolist())
            selected_city = st.selectbox("1. Select City:", options=all_cities, key="dash_city")
            st.markdown("---")
            
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
                zoom = 14 if (selected_name != "All" or selected_v_id != "All") else 12 if selected_chain != "All" else 11 if selected_city != "All" else 6
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
                        "weight": 1.0,
                        "fillOpacity": 0.15
                    },
                    tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Area Name: "])
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
                    
            st_folium(m, width="100%", height=650, key="main_map_admin", returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal
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

            map_radius_km = st.slider("Map View Radius (km):", min_value=3, max_value=35, value=10, step=1)
            portal_areas = get_nearby_polygons(v_row["lat"], v_row["lng"], map_radius_km)
            
            # ترتيب من الأكبر للأصغر لضمان أن المربعات الصغيرة تُرسم فوق المربعات الأكبر
            portal_areas = portal_areas.sort_values(by="area_size", ascending=False)
            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())

            if "vendor_portal_id" not in st.session_state or st.session_state["vendor_portal_id"] != v_id_clean:
                st.session_state["vendor_portal_id"] = v_id_clean
                initial_covered = portal_areas["Delivery Location Area Name"].head(2).tolist()
                st.session_state["vendor_multiselect"] = list(initial_covered)
                st.session_state["applied_zones"] = list(initial_covered)
                st.session_state["last_click_sig"] = None
                st.session_state["ms_version"] = 0
                st.session_state["show_pricing_table"] = False

            current_applied = st.session_state.get("applied_zones", [])

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])

            # ---------------- عمود الخريطة ----------------
            with col_map:
                st.subheader(f"🗺️ Map ({len(current_applied)} Zones Applied)")
                st.caption("Click any zone directly on the map to add it to the search box.")

                v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=13)
                folium.Marker(
                    location=[v_row["lat"], v_row["lng"]],
                    popup=f"<b>{v_name}</b>",
                    tooltip="Store Location",
                    icon=folium.Icon(color="green", icon="star")
                ).add_to(v_map)

                applied_set = set(current_applied)

                def vendor_zone_style(feature):
                    name = feature["properties"]["Delivery Location Area Name"]
                    if name in applied_set:
                        return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.55}
                    else:
                        return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.2, "fillOpacity": 0.18}

                folium.GeoJson(
                    portal_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                    name="Delivery Zones",
                    style_function=vendor_zone_style,
                    tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Zone: "])
                ).add_to(v_map)

                map_data = st_folium(
                    v_map,
                    width="100%",
                    height=500,
                    key=f"vmap_{v_id_clean}_{map_radius_km}",
                    returned_objects=["last_clicked", "last_object_clicked"]
                )

                # معالجة النقر بدقة تامة لإضافة المنطقة لمربع البحث
                if map_data:
                    clicked_zone = None
                    sig = None

                    # 1. فحص كائن المضلع المضغوط مباشرة
                    obj_clicked = map_data.get("last_object_clicked")
                    if obj_clicked and isinstance(obj_clicked, dict) and "properties" in obj_clicked:
                        clicked_zone = obj_clicked["properties"].get("Delivery Location Area Name")
                        sig = f"obj_{clicked_zone}"

                    # 2. فحص إحداثيات النقطة إذا لم يعد الكائن المباشر
                    if not clicked_zone and map_data.get("last_clicked"):
                        c = map_data["last_clicked"]
                        if isinstance(c, dict) and "lat" in c and "lng" in c:
                            sig = f"coords_{c['lat']:.5f}_{c['lng']:.5f}"
                            pt = Point(c["lng"], c["lat"])
                            matches = portal_areas[portal_areas.geometry.contains(pt)].sort_values(by="area_size", ascending=True)
                            if matches.empty:
                                dists = portal_areas.geometry.distance(pt)
                                if not dists.empty and dists.min() < 0.005:
                                    matches = portal_areas.loc[[dists.idxmin()]]
                            if not matches.empty:
                                clicked_zone = matches.iloc[0]["Delivery Location Area Name"]

                    # إضافة أو حذف المنطقة من قائمة مربع البحث فوراً
                    if clicked_zone and sig != st.session_state.get("last_click_sig"):
                        st.session_state["last_click_sig"] = sig
                        curr_search = list(st.session_state.get("vendor_multiselect", []))
                        if clicked_zone in curr_search:
                            curr_search.remove(clicked_zone)
                        else:
                            curr_search.append(clicked_zone)
                            
                        st.session_state["vendor_multiselect"] = curr_search
                        st.session_state["ms_version"] += 1
                        st.session_state["show_pricing_table"] = False
                        st.rerun()

            # ---------------- عمود مربع البحث ----------------
            with col_form:
                st.subheader("📝 Selected Zones")
                st.caption("Zones you click on the map will automatically appear here:")

                widget_key = f"ms_box_{st.session_state.get('ms_version', 0)}"
                chosen_zones = st.multiselect(
                    "Service Areas:",
                    options=all_available_zones,
                    default=st.session_state.get("vendor_multiselect", []),
                    key=widget_key
                )

                if chosen_zones != st.session_state.get("vendor_multiselect", []):
                    st.session_state["vendor_multiselect"] = chosen_zones

                btn_col1, btn_col2 = st.columns([1, 1])
                
                with btn_col1:
                    if st.button("👁️ Apply to Map", type="secondary", use_container_width=True):
                        st.session_state["applied_zones"] = list(st.session_state["vendor_multiselect"])
                        st.session_state["show_pricing_table"] = False
                        st.rerun()
                        
                with btn_col2:
                    if st.button("🚀 Submit Selection", type="primary", use_container_width=True):
                        if not st.session_state.get("applied_zones"):
                            st.warning("Please select and 'Apply to Map' at least one zone first.")
                        elif set(st.session_state.get("applied_zones", [])) != set(st.session_state.get("vendor_multiselect", [])):
                            st.warning("You have unapplied changes! Please click 'Apply to Map' first.")
                        else:
                            st.session_state["show_pricing_table"] = True
                            st.rerun()

            # ==========================================
            # 4. جدول التسعير والمسافات
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
    
    file_path = "vendor_pricing_requests.csv"
    if os.path.exists(file_path):
        try:
            raw_df = pd.read_csv(file_path)
            
            if "Zone" not in raw_df.columns:
                st.warning("⚠️ Legacy data format detected. The old database format is incompatible and has been cleared.")
                os.remove(file_path)
                st.rerun()
            else:
                raw_df["Vendor ID"] = raw_df["Vendor ID"].astype(str)
                
                st.write("### 🔍 Filter Requests")
                f_col1, f_col2 = st.columns(2)
                
                all_req_names = ["All"] + sorted(raw_df["Vendor Name"].dropna().unique().tolist())
                filter_name = f_col1.selectbox("Filter by Vendor Name:", all_req_names, key="admin_req_name")
                
                if filter_name != "All":
                    temp_req_ids = raw_df[raw_df["Vendor Name"] == filter_name]["Vendor ID"].dropna().unique().tolist()
                else:
                    temp_req_ids = raw_df["Vendor ID"].dropna().unique().tolist()
                    
                all_req_ids = ["All"] + sorted(temp_req_ids)
                filter_id = f_col2.selectbox("Filter by Vendor ID:", all_req_ids, key="admin_req_id")
                
                filtered_raw = raw_df.copy()
                if filter_name != "All":
                    filtered_raw = filtered_raw[filtered_raw["Vendor Name"] == filter_name]
                if filter_id != "All":
                    filtered_raw = filtered_raw[filtered_raw["Vendor ID"] == filter_id]
                    
                display_df = filtered_raw.groupby(["Date", "Vendor ID", "Vendor Name", "Status"]).agg(
                    Total_Zones=("Zone", "count"),
                    Zones_Preview=("Zone", lambda x: ", ".join(x.head(3)) + ("..." if len(x) > 3 else ""))
                ).reset_index()
                display_df.rename(columns={"Total_Zones": "Total Zones Count", "Zones_Preview": "Zones Overview"}, inplace=True)
                
                st.markdown("---")
                display_df.insert(0, "Select", False)
                
                st.write(f"### 📋 Incoming Requests Overview ({len(display_df)} requests)")
                st.caption("Check the boxes to select requests. The downloaded file will contain detailed row-by-row data for each zone.")
                
                edited_display_df = st.data_editor(
                    display_df,
                    column_config={
                        "Select": st.column_config.CheckboxColumn("Select", help="Select to download", default=False),
                        "Date": st.column_config.TextColumn(disabled=True),
                        "Vendor ID": st.column_config.TextColumn(disabled=True),
                        "Vendor Name": st.column_config.TextColumn(disabled=True),
                        "Total Zones Count": st.column_config.NumberColumn(disabled=True),
                        "Zones Overview": st.column_config.TextColumn(disabled=True),
                        "Status": st.column_config.TextColumn(disabled=True)
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="admin_requests_editor"
                )
                
                selected_displays = edited_display_df[edited_display_df["Select"] == True]
                
                st.markdown("---")
                col_down1, col_down2 = st.columns([7, 3])
                
                with col_down1:
                    st.write("#### 💾 Download Selected Requests")
                    if selected_displays.empty:
                        st.info("Select one or more requests from the table above to download the detailed CSV.")
                    else:
                        selected_vendors_dates = selected_displays[["Vendor ID", "Date"]].apply(tuple, axis=1).tolist()
                        download_df = raw_df[raw_df[["Vendor ID", "Date"]].apply(tuple, axis=1).isin(selected_vendors_dates)]
                        
                        csv_data = download_df.to_csv(index=False).encode('utf-8-sig')
                        
                        if len(selected_displays) == 1:
                            v_name = selected_displays.iloc[0]['Vendor Name']
                            file_name = f"Detailed_Pricing_{v_name}.csv"
                            st.success(f"1 Request selected. The file contains {len(download_df)} detailed zone rows.")
                        else:
                            file_name = "Combined_Detailed_Pricing.csv"
                            st.success(f"{len(selected_displays)} Requests selected. The file contains {len(download_df)} combined zone rows.")
                            
                        st.download_button(
                            label="📥 Download Detailed CSV (Row per Zone)",
                            data=csv_data,
                            file_name=file_name,
                            mime="text/csv",
                            type="primary"
                        )
                        
                with col_down2:
                    st.write("#### 🗑️ Clear Database")
                    st.warning("Delete all requests permanently.")
                    if st.button("Delete All Requests Data", type="secondary"):
                        os.remove("vendor_pricing_requests.csv")
                        st.rerun()

        except Exception as e:
            st.error("A critical format error occurred with the database file.")
            if st.button("Force Clear Corrupted Data", type="primary"):
                os.remove("vendor_pricing_requests.csv")
                st.rerun()
    else:
        st.info("No detailed requests received yet. Wait for vendors to submit.")
