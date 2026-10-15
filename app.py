import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely import wkt
import plotly.express as px
import plotly.graph_objects as go
import re
import os
import json
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
    
    gdf_a['id'] = gdf_a.index.astype(str)
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.002, preserve_topology=False)
    
    # Generate JSON string inside the cached load function to prevent unhashable cache errors
    geojson_dict = json.loads(gdf_a.to_json())
    
    return df_v, gdf_a, geojson_dict

df_vendors, gdf_areas, full_geojson = load_data()

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
    st.header("Zones & Vendors Dashboard")
    st.info("The Admin Map is kept simple in this version to focus on the Vendor Portal Plotly implementation.")

with tab2:
    st.header("Vendor Portal - Coverage Zones Management")
    st.info("🎯 Use the Box Select or Lasso Select tool on the map to highlight multiple areas instantly!")
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
            
            all_available_areas = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())
            
            if "portal_vendor_id" not in st.session_state or st.session_state["portal_vendor_id"] != v_id_clean:
                st.session_state["portal_vendor_id"] = v_id_clean
                initial_covered = gdf_areas["Delivery Location Area Name"].head(3).tolist()
                st.session_state["selected_zones"] = list(initial_covered)
                st.session_state["vendor_multiselect"] = list(initial_covered)

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])
            
            with col_map:
                st.subheader("🗺️ Coverage Map (Lasso/Box Select)")
                st.caption("🔍 In the top right corner of the map, click the **Lasso icon** (حبل) or **Box icon** (مربع). Then draw around the zones you want to select!")
                
                df_plot = gdf_areas[['id', 'Delivery Location Area Name']].copy()
                df_plot['Status'] = 'Available'
                df_plot.loc[df_plot['Delivery Location Area Name'].isin(st.session_state["selected_zones"]), 'Status'] = 'Covered'
                
                fig = px.choropleth_mapbox(
                    df_plot,
                    geojson=full_geojson,
                    locations='id',
                    featureidkey="properties.id",
                    color='Status',
                    color_discrete_map={'Available': '#3388ff', 'Covered': '#28a745'},
                    hover_name='Delivery Location Area Name',
                    mapbox_style="carto-positron",
                    zoom=11,
                    center={"lat": float(v_row["lat"]), "lon": float(v_row["lng"])},
                    opacity=0.4
                )
                
                fig.add_trace(go.Scattermapbox(
                    lat=[float(v_row["lat"])],
                    lon=[float(v_row["lng"])],
                    mode='markers+text',
                    marker=go.scattermapbox.Marker(size=14, color='red'),
                    text=[v_name],
                    textposition="bottom right",
                    hoverinfo='text'
                ))
                
                fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, uirevision='constant')
                
                try:
                    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode=('points', 'box', 'lasso'))
                    
                    if event and "selection" in event and event["selection"]["points"]:
                        selected_indices = [p["location"] for p in event["selection"]["points"] if "location" in p]
                        if selected_indices:
                            selected_names = df_plot[df_plot["id"].isin(selected_indices)]["Delivery Location Area Name"].tolist()
                            
                            new_set = set(st.session_state["selected_zones"]).union(set(selected_names))
                            if new_set != set(st.session_state["selected_zones"]):
                                st.session_state["selected_zones"] = list(new_set)
                                st.session_state["vendor_multiselect"] = list(new_set)
                                st.rerun()
                except TypeError:
                    st.plotly_chart(fig, use_container_width=True)
                    st.warning("Your Streamlit version doesn't support Plotly Lasso return. Please use the form on the right.")

            with col_form:
                st.subheader("📝 Selected Zones")
                st.caption("You can also add/remove manually here.")
                
                def sync_from_multiselect():
                    st.session_state["selected_zones"] = list(st.session_state["vendor_multiselect"])

                st.multiselect(
                    "Service Areas:",
                    options=all_available_areas,
                    default=st.session_state["selected_zones"],
                    key="vendor_multiselect",
                    on_change=sync_from_multiselect
                )
                
                if st.button("🧹 Clear All Zones", type="secondary"):
                    st.session_state["selected_zones"] = []
                    st.session_state["vendor_multiselect"] = []
                    st.rerun()

                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 Submit Modification Request", type="primary", use_container_width=True):
                    final_selected = st.session_state["selected_zones"]
                    if not final_selected:
                        st.warning("No zones selected!")
                    else:
                        save_modification_request(v_id_clean, v_name, [], final_selected)
                        st.success(f"✅ Modification request for {len(final_selected)} zones submitted successfully!")

with tab3:
    st.header("📥 Vendor Coverage Change Requests")
    if os.path.exists("vendor_requests.csv"):
        req_df = pd.read_csv("vendor_requests.csv")
        st.dataframe(req_df, use_container_width=True)
        with open("vendor_requests.csv", "rb") as file:
            st.download_button(label="📥 Download Requests Log (CSV)", data=file, file_name="vendor_coverage_updates.csv", mime="text/csv")
    else:
        st.info("No modification requests received yet.")
