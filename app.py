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
    
    # تبسيط المضلعات لتسريع العرض التفاعلي
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.002, preserve_topology=False)
    return df_v, gdf_a

df_vendors, gdf_areas = load_data()

def save_modification_request(vendor_id, vendor_name, zones_list):
    request_data = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Vendor ID": vendor_id,
        "Vendor Name": vendor_name,
        "Total Zones Count": len(zones_list),
        "Requested Zones": ", ".join(zones_list),
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
                
        st_folium(m, width="100%", height=600, key="main_map_admin", returned_objects=[])

# Tab 2: Vendor Portal
with tab2:
    st.header("Vendor Portal - Coverage Zones Management")
    st.info("Enter your Vendor ID to view your store location and configure your delivery coverage areas.")
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

            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())

            # State initialization
            if "vendor_portal_id" not in st.session_state or st.session_state["vendor_portal_id"] != v_id_clean:
                st.session_state["vendor_portal_id"] = v_id_clean
                st.session_state["active_zones"] = []
                st.session_state["staged_selection"] = []

            st.markdown("---")
            st.subheader(f"🗺️ Coverage Map ({len(st.session_state['active_zones'])} Zones Applied)")
            st.caption("💡 **Tip:** Click on any zone on the map to view its name and copy it to clipboard with 1 click!")

            col_l1, col_l2 = st.columns(2)
            col_l1.markdown("🟢 **Green Areas:** Applied & Verified (Delivering here)")
            col_l2.markdown("🔵 **Blue Areas:** Available nearby zones")

            # عرض المضلعات المحيطة بالفيندور + أي مناطق مختارة
            v_point = Point(v_row["lng"], v_row["lat"])
            nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(0.30))
            active_mask = gdf_areas["Delivery Location Area Name"].isin(st.session_state["active_zones"])
            portal_display_areas = gdf_areas[nearby_mask | active_mask].copy()

            v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=12)

            folium.Marker(
                location=[v_row["lat"], v_row["lng"]],
                popup=f"<b>{v_name}</b><br>Store Location",
                tooltip=v_name,
                icon=folium.Icon(color="green", icon="star")
            ).add_to(v_map)

            active_set = set(st.session_state["active_zones"])

            def vendor_zone_style(feature):
                name = feature["properties"]["Delivery Location Area Name"]
                if name in active_set:
                    return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.55}
                else:
                    return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.0, "fillOpacity": 0.15}

            folium.GeoJson(
                portal_display_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                name="Delivery Zones",
                style_function=vendor_zone_style,
                tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Zone: "]),
                popup=folium.GeoJsonPopup(fields=["Delivery Location Area Name"], aliases=["Zone Name: "])
            ).add_to(v_map)

            # كود جافاسكريبت لنسخ اسم المنطقة تلقائياً للحافظة عند فتح النافذة المنبثقة
            copy_script = """
            <script>
            document.addEventListener('DOMContentLoaded', function() {
                var observer = new MutationObserver(function(mutations) {
                    mutations.forEach(function(mutation) {
                        mutation.addedNodes.forEach(function(node) {
                            if (node.classList && node.classList.contains('leaflet-popup')) {
                                var content = node.querySelector('.leaflet-popup-content');
                                if (content && !content.querySelector('.copy-btn')) {
                                    var td = content.querySelector('td') || content;
                                    var zoneName = td.innerText.replace('Zone Name:', '').trim();
                                    
                                    try {
                                        navigator.clipboard.writeText(zoneName);
                                    } catch(e) {}
                                    
                                    var btn = document.createElement('button');
                                    btn.className = 'copy-btn';
                                    btn.innerHTML = '📋 Click to Copy: ' + zoneName;
                                    btn.style = 'margin-top:8px; padding:6px 12px; background:#28a745; color:white; border:none; border-radius:4px; cursor:pointer; width:100%; font-weight:bold; font-size:12px;';
                                    btn.onclick = function() {
                                        navigator.clipboard.writeText(zoneName);
                                        btn.innerHTML = '✅ Copied to Clipboard!';
                                        setTimeout(function(){ btn.innerHTML = '📋 Click to Copy: ' + zoneName; }, 1800);
                                    };
                                    content.appendChild(btn);
                                }
                            }
                        });
                    });
                });
                observer.observe(document.body, { childList: true, subtree: true });
            });
            </script>
            """
            v_map.get_root().html.add_child(folium.Element(copy_script))

            # returned_objects=[] يجعل الخريطة تعمل بنعومة كاملة وبدون أي إعادة تحميل عند النقر
            st_folium(v_map, width="100%", height=480, key="portal_map_view", returned_objects=[])

            st.markdown("---")
            st.subheader("📝 Selected Delivery Zones")
            st.caption("Paste or search for the zone names below. Use **Apply** to preview them in Green on the map, then **Submit** to finalize.")

            chosen_zones = st.multiselect(
                "Delivery Zones Selection:",
                options=all_available_zones,
                default=st.session_state.get("staged_selection", st.session_state["active_zones"]),
                key="vendor_multiselect_box"
            )

            # زرا Apply و Submit جنباً إلى جنب
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
            
            with btn_col1:
                apply_clicked = st.button("👁️ Apply (Preview on Map)", type="secondary", use_container_width=True)
                
            with btn_col2:
                submit_clicked = st.button("🚀 Submit to Admin", type="primary", use_container_width=True)

            if apply_clicked:
                st.session_state["active_zones"] = chosen_zones
                st.session_state["staged_selection"] = chosen_zones
                st.toast(f"Updated! {len(chosen_zones)} zones are now highlighted in Green on the map.", icon="🟢")
                st.rerun()

            if submit_clicked:
                if not chosen_zones:
                    st.warning("Please select at least one zone before submitting.")
                else:
                    st.session_state["active_zones"] = chosen_zones
                    st.session_state["staged_selection"] = chosen_zones
                    save_modification_request(v_id_clean, v_name, chosen_zones)
                    st.success(f"🎉 Success! Request for {len(chosen_zones)} zones submitted to Admin and saved.")
                    st.rerun()

# Tab 3: Admin Review
with tab3:
    st.header("📥 Vendor Coverage Change Requests")
    if os.path.exists("vendor_requests.csv"):
        req_df = pd.read_csv("vendor_requests.csv")
        st.dataframe(req_df, use_container_width=True)
        with open("vendor_requests.csv", "rb") as file:
            st.download_button(label="📥 Download Requests Log (CSV)", data=file, file_name="vendor_coverage_updates.csv", mime="text/csv")
    else:
        st.info("No modification requests received yet.")
