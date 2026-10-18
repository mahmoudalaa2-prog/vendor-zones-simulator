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
import io
import requests
from datetime import datetime

# ==========================================
# 1. إعدادات الصفحة واللغة
# ==========================================
st.set_page_config(layout="wide", page_title="Pharmacy & Zones Management", page_icon="💊")

if "lang" not in st.session_state:
    st.session_state["lang"] = "ar"

def T(ar_text, en_text):
    return ar_text if st.session_state.get("lang", "ar") == "ar" else en_text

BRANCH_PALETTE = [
    {"hex": "#28a745", "folium": "green", "name": "أخضر"},
    {"hex": "#e67e22", "folium": "orange", "name": "برتقالي"},
    {"hex": "#9b59b6", "folium": "purple", "name": "بنفسجي"},
    {"hex": "#e74c3c", "folium": "red", "name": "أحمر"},
    {"hex": "#17a2b8", "folium": "cadetblue", "name": "تركواز"},
    {"hex": "#d63384", "folium": "pink", "name": "وردي"},
    {"hex": "#0dcaf0", "folium": "lightblue", "name": "سماوي"},
    {"hex": "#198754", "folium": "darkgreen", "name": "أخضر داكن"},
    {"hex": "#8540f5", "folium": "darkpurple", "name": "أرجواني"},
    {"hex": "#a52a2a", "folium": "darkred", "name": "بني"}
]

# ==========================================
# 2. إدارة المستخدمين وقاعدة البيانات الأمنية
# ==========================================
USERS_FILE = "users.csv"
REQUESTS_FILE = "vendor_pricing_requests.csv"

def init_users_db():
    if not os.path.exists(USERS_FILE):
        pd.DataFrame([{
            "email": "mahmoud.alaa.2@talabat.com",
            "password": "123456",
            "role": "admin",
            "access_type": "all",
            "access_ids": "all"
        }]).to_csv(USERS_FILE, index=False)

def get_users_df():
    init_users_db()
    return pd.read_csv(USERS_FILE)

def add_user(email, password, role, access_type="all", access_ids="all"):
    df = get_users_df()
    email_clean = email.strip().lower()
    if email_clean in df["email"].str.lower().values:
        return False, "هذا البريد مسجل بالفعل!"
    new_user = pd.DataFrame([{
        "email": email_clean,
        "password": str(password).strip(),
        "role": role,
        "access_type": access_type,
        "access_ids": access_ids
    }])
    df = pd.concat([df, new_user], ignore_index=True)
    df.to_csv(USERS_FILE, index=False)
    return True, "تم إنشاء الحساب بنجاح!"

def update_user_permissions(email, role, access_type, access_ids):
    df = get_users_df()
    email_clean = email.strip().lower()
    idx = df[df["email"].str.lower() == email_clean].index
    if not idx.empty:
        df.loc[idx, "role"] = role
        df.loc[idx, "access_type"] = access_type
        df.loc[idx, "access_ids"] = access_ids
        df.to_csv(USERS_FILE, index=False)
        return True, "تم تحديث الصلاحيات بنجاح!", df.iloc[idx[0]].to_dict()
    return False, "المستخدم غير موجود.", None

def delete_user(email):
    df = get_users_df()
    if email.strip().lower() == "mahmoud.alaa.2@talabat.com":
        return False, "لا يمكن حذف الأدمن الرئيسي!"
    df = df[df["email"].str.lower() != email.strip().lower()]
    df.to_csv(USERS_FILE, index=False)
    return True, "تم حذف الحساب بنجاح!"

# ==========================================
# 3. دوال المعالجة
# ==========================================
def normalize_id(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    return re.sub(r"\.0+$", "", s)

def parse_yes_no(val, default="Yes"):
    if pd.isna(val) or str(val).strip().lower() in ["", "none", "nan", "null"]: return default
    return "Yes" if str(val).strip().lower() in ["yes", "y", "true", "1"] else "No"

def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str): return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def get_col(df, possible_names):
    if df.empty: return None
    for name in possible_names:
        for col in df.columns:
            if str(name).strip().lower() == str(col).strip().lower(): return col
    for name in possible_names:
        name_clean = re.sub(r'[^a-zA-Z0-9]', '', str(name)).lower()
        for col in df.columns:
            if name_clean == re.sub(r'[^a-zA-Z0-9]', '', str(col)).lower(): return col
    return None

def read_google_sheet_csv(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        if "export?format=csv" not in url:
            m = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
            gid = re.search(r"[#&?]gid=([0-9]+)", url)
            if m: url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid.group(1) if gid else '0'}"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200 and not any(tag in res.text[:500].lower() for tag in ["<!doctype", "<html", "google accounts"]):
            return pd.read_csv(io.StringIO(res.text))
    except: pass
    return pd.DataFrame()

# ==========================================
# 4. جلب وتجهيز البيانات
# ==========================================
@st.cache_data(ttl=1800)
def load_data():
    url_vendors = "https://docs.google.com/spreadsheets/d/12SSMW20Two2hRpHOuIXXifweJI82bZpJClhUAWSuYHk/export?format=csv&gid=0"
    url_areas = "https://docs.google.com/spreadsheets/d/1Y3AlqaHjp4nZup6QwOBgl6CT5z3XHjfzpRSx5Yw5byk/export?format=csv&gid=0"
    url_delivery = "https://docs.google.com/spreadsheets/d/1Gh6xnGNn7yx2g-bdIHC4DvHIMzVkOnh3Fdy6AhQtTmM/export?format=csv&gid=540443526"
    url_performance = "https://docs.google.com/spreadsheets/d/1u_VDm8bejb8gpooW7hqSCUNQ8ZqJ-4myQ_cTvqUfRZQ/export?format=csv&gid=0"

    df_v, df_a, df_d, df_p = map(read_google_sheet_csv, [url_vendors, url_areas, url_delivery, url_performance])

    if not df_v.empty:
        df_v["clean_vid"] = df_v[get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID"])].apply(normalize_id)
        df_v["clean_cid"] = df_v[get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID"])].apply(normalize_id)
        df_v["clean_name"] = df_v[get_col(df_v, ["Vendor Attributes Vendor Name (English)", "Vendor Name"])].astype(str).str.strip()
        df_v["clean_chain_name"] = df_v[get_col(df_v, ["Chain Attributes Chain Name", "Chain Name"])].astype(str).str.strip()
        df_v["clean_city"] = df_v[get_col(df_v, ["Vendor Attributes Vendor City", "City"])].astype(str).str.strip()
        am_c = get_col(df_v, ["Vendor Attributes Account Manager", "Account Manager", "AM"])
        df_v["clean_am"] = df_v[am_c].astype(str).str.strip() if am_c else "-"
        act_c, hid_c = get_col(df_v, ["Vendor Attributes Is Active", "Is Active"]), get_col(df_v, ["Vendor Attributes Is Hidden", "Is Hidden"])
        df_v["clean_active"] = df_v[act_c].apply(lambda x: parse_yes_no(x, "Yes")) if act_c else "Yes"
        df_v["clean_hidden"] = df_v[hid_c].apply(lambda x: parse_yes_no(x, "No")) if hid_c else "No"
        
        loc_c = get_col(df_v, ["Vendor Attributes Vendor Map Location", "Map Location", "Location"])
        if loc_c:
            c = df_v[loc_c].astype(str).str.split(r'[,;]+', expand=True)
            df_v["lat"], df_v["lng"] = pd.to_numeric(c[0], errors="coerce"), pd.to_numeric(c[1], errors="coerce")
        else:
            df_v["lat"], df_v["lng"] = np.nan, np.nan
        df_v = df_v[df_v["clean_vid"] != ""].copy()

    if not df_p.empty:
        df_p["clean_vid"] = df_p[get_col(df_p, ["Vendor ID"])].apply(normalize_id)
        df_p["clean_cid"] = df_p[get_col(df_p, ["Chain ID"])].apply(normalize_id)
        df_p["qc_orders"] = df_p[get_col(df_p, ["QC Net Orders"])]
        df_p["fail_orders"] = df_p[get_col(df_p, ["Vendor Net Failed Orders"])]
        df_p["fail_rate"] = df_p[get_col(df_p, ["Vendor Net Fail Rate"])]
        df_p["contact_rate"] = df_p[get_col(df_p, ["Contact Rate"])]
        df_p["fault_cr"] = df_p[get_col(df_p, ["Vendor Fault Customer Contact Rate"])]

    if not df_d.empty and not df_v.empty:
        df_d["clean_vid"] = df_d[get_col(df_d, ["Vendor ID"])].apply(normalize_id)
        df_d["clean_cid"] = df_d[get_col(df_d, ["Chain ID"])].apply(normalize_id)
        df_d["clean_zone"] = df_d[get_col(df_d, ["Area Name", "Zone"])].astype(str).str.strip()
        df_d["clean_time"] = df_d[get_col(df_d, ["Delivery Time", "Time"])].astype(str).str.strip()
        df_d["clean_fee"] = df_d[get_col(df_d, ["Delivery Fees", "Fee"])].astype(str).str.strip()
        mask = (df_d["clean_vid"].isin(set(df_v["clean_vid"]))) | (df_d["clean_cid"].isin(set(df_v["clean_cid"])))
        df_d = df_d[mask].copy()

    if not df_a.empty:
        poly_col = get_col(df_a, ["Delivery Location Area Polygon", "Polygon"])
        if poly_col:
            df_a["cleaned_wkt"] = df_a[poly_col].apply(clean_wkt)
            geoms, idxs = [], []
            for i, w in df_a["cleaned_wkt"].items():
                if pd.notnull(w):
                    try:
                        geoms.append(wkt.loads(w)); idxs.append(i)
                    except: pass
            gdf_a = gpd.GeoDataFrame(df_a.loc[idxs], geometry=geoms, crs="EPSG:4326")
            gdf_a["area_size"] = gdf_a.area
            an = get_col(gdf_a, ["Delivery Location Area Name", "Area Name"])
            if an:
                gdf_a["Delivery Location Area Name"] = gdf_a[an].astype(str).str.strip()
                gdf_a = gdf_a[(~gdf_a["Delivery Location Area Name"].str.contains(r"mcd|mcdonald", case=False)) & (gdf_a["area_size"] < 0.5)].copy()
            gdf_a = gdf_a.sort_values("area_size", ascending=False)
            gdf_a["centroid_lat"], gdf_a["centroid_lng"] = gdf_a.centroid.y, gdf_a.centroid.x
            gdf_a["geometry"] = gdf_a["geometry"].simplify(0.0005, preserve_topology=True)
        else: gdf_a = gpd.GeoDataFrame()
    else: gdf_a = gpd.GeoDataFrame()

    return df_v, gdf_a, df_d, df_p

df_vendors, gdf_areas, df_delivery, df_performance = load_data()

def get_user_vendors(user_dict, df_v):
    if df_v.empty: return pd.DataFrame()
    acc_type, acc_ids = user_dict.get("access_type", "all"), [normalize_id(x) for x in str(user_dict.get("access_ids", "")).split(",") if x.strip()]
    if acc_type == "all" or "all" in acc_ids: return df_v.copy()
    if acc_type == "Chain ID": return df_v[df_v["clean_cid"].isin(acc_ids)].copy()
    return df_v[df_v["clean_vid"].isin(acc_ids)].copy()

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    if gdf_areas.empty or pd.isna(lat) or pd.isna(lng): return gpd.GeoDataFrame()
    return gdf_areas[gdf_areas.geometry.intersects(Point(lng, lat).buffer(radius_km / 111.0))].copy()

def init_requests_db():
    if not os.path.exists(REQUESTS_FILE):
        pd.DataFrame(columns=["Date", "Vendor ID", "Vendor Name", "Zone", "Classification", "Action", "Distance (km)", "Delivery Time", "Delivery Fees", "Final_Status", "Status"]).to_csv(REQUESTS_FILE, index=False)

def save_detailed_request(vendor_id, vendor_name, edited_df):
    init_requests_db()
    save_df = edited_df.copy()
    save_df.insert(0, "Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    save_df.insert(1, "Vendor ID", str(vendor_id))
    save_df.insert(2, "Vendor Name", vendor_name)
    save_df["Status"] = "Pending"
    save_df.to_csv(REQUESTS_FILE, mode="a", header=False, index=False)

def get_perf(vid, cid, df_p):
    v_p, c_p = {}, {}
    if not df_p.empty:
        v_m = df_p[df_p["clean_vid"] == str(vid)]
        if not v_m.empty: v_p = v_m.iloc[0].to_dict()
        if cid:
            c_m = df_p[df_p["clean_cid"] == str(cid)]
            if not c_m.empty:
                try:
                    q_sum, f_sum = pd.to_numeric(c_m["qc_orders"], errors="coerce").sum(), pd.to_numeric(c_m["fail_orders"], errors="coerce").sum()
                    c_p = {"qc_orders": int(q_sum) if pd.notna(q_sum) else "-", "fail_orders": int(f_sum) if pd.notna(f_sum) else "-", "fail_rate": f"{(f_sum/q_sum*100):.1f}%" if q_sum>0 else "-", "contact_rate": c_m["contact_rate"].iloc[0] if "contact_rate" in c_m else "-", "fault_cr": c_m["fault_cr"].iloc[0] if "fault_cr" in c_m else "-"}
                except: c_p = c_m.iloc[0].to_dict()
    return v_p, c_p

def build_popup_html(r, df_d, df_p):
    vid, cid, nm, cnm, is_act, is_hid = str(r.get("clean_vid","")), str(r.get("clean_cid","")), str(r.get("clean_name","")), str(r.get("clean_chain_name","")), r.get("clean_active","Yes"), r.get("clean_hidden","No")
    vp, _ = get_perf(vid, cid, df_p)
    bdg1 = "<span style='color:#198754;'>🟢 نشط</span>" if is_act == "Yes" else "<span style='color:#dc3545;'>🔴 غير نشط</span>"
    bdg2 = " | <span style='color:#fd7e14;'>👁️ مخفي</span>" if is_hid == "Yes" else ""
    html = f"<div style='font-family: Arial; width: 280px; font-size: 12px;'><h4 style='color:#0d6efd; margin:0 0 4px;'>💊 {nm}</h4><b>Vendor:</b> {vid} | <b>Chain:</b> {cnm}<br><b>الحالة:</b> {bdg1}{bdg2}<hr style='margin:4px 0;'>"
    if vp:
        html += f"<div style='background:#f8f9fa; padding:4px;'><b style='color:#0d6efd;'>📊 مؤشرات الأداء:</b><table style='width:100%; font-size:11px;'><tr><td>QC Orders:</td><td align='right'><b>{vp.get('qc_orders','-')}</b></td></tr><tr><td>Failed Orders:</td><td align='right'>{vp.get('fail_orders','-')} ({vp.get('fail_rate','-')})</td></tr><tr><td>Contact Rate:</td><td align='right'>{vp.get('contact_rate','-')}</td></tr><tr><td>Fault CR:</td><td align='right'>{vp.get('fault_cr','-')}</td></tr></table></div>"
    md = df_d[df_d["clean_vid"] == vid] if not df_d.empty else pd.DataFrame()
    if not md.empty and "clean_zone" in md:
        html += f"<b style='color:#198754;'>🛵 مناطق التوصيل ({len(md['clean_zone'].unique())}):</b><div style='max-height:100px; overflow-y:auto;'><table style='width:100%; font-size:11px;'><tr style='background:#f8f9fa;'><th align='left'>Zone</th><th>Time</th><th>Fee</th></tr>"
        for _, x in md.iterrows():
            html += f"<tr style='border-bottom:1px solid #f1f1f1;'><td>{x.get('clean_zone','')}</td><td>{x.get('clean_time','')}</td><td>{x.get('clean_fee','')}</td></tr>"
        html += "</table></div>"
    else: html += "<div style='color:gray; font-size:11px;'>لا توجد مناطق مخصصة للفرع.</div>"
    return html + "</div>"

# ==========================================
# 5. Authentication
# ==========================================
init_users_db()
init_requests_db()
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if not st.session_state["logged_in"]:
    st.markdown(f"<h2 style='text-align: center;'>🔐 {T('تسجيل الدخول إلى النظام', 'System Login')}</h2>", unsafe_allow_html=True)
    _, col, _ = st.columns([1,1.5,1])
    with col:
        with st.form("login"):
            em = st.text_input(T("البريد الإلكتروني:", "Email:")).strip().lower()
            pw = st.text_input(T("كلمة المرور:", "Password:"), type="password").strip()
            if st.form_submit_button(T("تسجيل الدخول", "Login"), type="primary", use_container_width=True):
                udf = get_users_df()
                m = udf[(udf["email"].str.lower() == em) & (udf["password"].astype(str) == pw)]
                if not m.empty:
                    st.session_state.update({"logged_in": True, "current_user": m.iloc[0].to_dict()})
                    st.rerun()
                else: st.error(T("البيانات غير صحيحة.", "Invalid credentials."))
    st.stop()

c_user = st.session_state["current_user"]
is_admin = c_user["role"] == "admin"
user_vendors = get_user_vendors(c_user, df_vendors)
t_v = len(user_vendors)
a_v = len(user_vendors[user_vendors["clean_active"] == "Yes"]) if t_v else 0

with st.sidebar:
    st.session_state["lang"] = "ar" if st.radio("🌐 Language", ["العربية", "English"], index=0 if st.session_state.get("lang")=="ar" else 1, horizontal=True) == "العربية" else "en"
    st.markdown("---")
    st.write(f"👤 **{T('المستخدم', 'User')}:** `{c_user['email']}`")
    st.metric(T("🏬 الفروع التابعة لك", "Your Branches"), t_v, f"🟢 {a_v} نشط")
    if is_admin: st.metric(T("🗺️ إجمالي المناطق", "Total Zones"), len(gdf_areas))
    st.session_state.setdefault("last_sync", datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"))
    if st.button(T("🔄 مزامنة البيانات الآن", "Sync Data Now"), use_container_width=True):
        st.cache_data.clear(); st.session_state["last_sync"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"); st.rerun()
    st.caption(f"🕒 {st.session_state['last_sync']}")
    if st.button(T("🚪 تسجيل الخروج", "Logout"), use_container_width=True):
        st.session_state.clear(); st.rerun()

if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs([T("🗺️ خريطة الإدارة", "Overview Map"), T("🛒 بوابة الفيندور", "Vendor Portal"), T("📥 الطلبات", "Requests"), T("👥 الحسابات", "Users")])
else: tab2 = st.container()

# ==========================================
# Tab 1: Admin Map
# ==========================================
if is_admin:
    with tab1:
        st.header(T("🗺️ خريطة الإدارة والمحاكاة", "Admin Overview Map"))
        if not st.toggle(T("⚡ تفعيل خريطة الإدارة", "Activate Map"), value=False):
            st.info(T("الخريطة معطلة لسرعة الأداء.", "Map disabled for performance."))
        else:
            c1, c2, c3, c4 = st.columns([1.2, 1.4, 1.4, 1.2])
            with c1:
                ac = [T("كل المدن", "All Cities")] + sorted([x for x in user_vendors["clean_city"].unique() if x]) if t_v else [T("كل المدن", "All Cities")]
                s_cit = st.selectbox(T("1. المدينة:", "City:"), ac)
            cdf = user_vendors if s_cit == T("كل المدن", "All Cities") else user_vendors[user_vendors["clean_city"]==s_cit]
            
            with c2:
                ams = [T("كل الـ AMs", "All AMs")] + sorted([a for a in cdf.get("clean_am", pd.Series()).unique() if a and a!="-"]) if "clean_am" in cdf else [T("كل الـ AMs", "All AMs")]
                s_am = st.selectbox(T("2. مسؤول (AM):", "AM:"), ams)
            adf = cdf if s_am == T("كل الـ AMs", "All AMs") else cdf[cdf["clean_am"]==s_am]

            with c3:
                cm = dict(zip(adf["clean_cid"], adf.get("clean_chain_name","") + " (" + adf["clean_cid"] + ")")) if not adf.empty else {}
                s_ch = st.selectbox(T("3. السلسلة:", "Chain:"), [T("كل السلاسل", "All Chains")] + list(cm.keys()), format_func=lambda x: cm.get(x, x))
            hdf = adf if s_ch == T("كل السلاسل", "All Chains") else adf[adf["clean_cid"]==s_ch]

            with c4:
                vm = dict(zip(hdf["clean_vid"], hdf.get("clean_name","") + " (" + hdf["clean_vid"] + ")")) if not hdf.empty else {}
                s_v = st.selectbox(T("4. الفرع:", "Vendor:"), [T("كل الفروع", "All Vendors")] + list(vm.keys()), format_func=lambda x: vm.get(x, x))

            f1, f2, f3 = st.columns([1.5, 1.5, 1.8])
            with f1: s_act = st.selectbox(T("5. حالة التفعيل:", "Active:"), [T("الكل", "All"), "Yes", "No"])
            with f2: s_hid = st.selectbox(T("6. حالة الظهور:", "Hidden:"), [T("الكل", "All"), "No", "Yes"])
            with f3:
                if st.button("🔄 Reset"): st.rerun()

            df_disp = hdf.copy()
            if s_v != T("كل الفروع", "All Vendors"): df_disp = df_disp[df_disp["clean_vid"]==s_v]
            if s_act in ["Yes", "No"]: df_disp = df_disp[df_disp.get("clean_active", "Yes") == s_act]
            if s_hid in ["Yes", "No"]: df_disp = df_disp[df_disp.get("clean_hidden", "No") == s_hid]

            pv = df_disp.dropna(subset=["lat", "lng"])
            vcmap = {}
            if s_ch != T("كل السلاسل", "All Chains"):
                for i, (_, r) in enumerate(hdf[["clean_vid","clean_name"]].drop_duplicates().iterrows()):
                    vcmap[r["clean_vid"]] = {"name": r["clean_name"], "hex": BRANCH_PALETTE[i%10]["hex"], "folium": BRANCH_PALETTE[i%10]["folium"]}
            elif s_v != T("كل الفروع", "All Vendors") and not display_vendors.empty:
                vcmap[s_v] = {"name": df_disp.iloc[0]["clean_name"], "hex": "#28a745", "folium": "green"}

            zvi = {}
            if not df_d.empty and vcmap:
                rdel = df_d[df_d["clean_vid"].isin(set(vcmap.keys()))]
                for _, r in rdel.iterrows():
                    z = str(r.get("clean_zone","")).strip().lower()
                    if z and (inf := vcmap.get(str(r["clean_vid"]))):
                        zvi.setdefault(z, []).append({"vid": r["clean_vid"], "name": inf["name"], "hex": inf["hex"], "time": r.get("clean_time","-"), "fee": r.get("clean_fee","-")})

            m_cent = [pv.iloc[0]["lat"], pv.iloc[0]["lng"]] if not pv.empty and s_v != T("كل الفروع", "All Vendors") else ([pv["lat"].mean(), pv["lng"].mean()] if not pv.empty else [30.04, 31.23])
            zm = 13 if s_v != T("كل الفروع", "All Vendors") else (11 if s_ch != T("كل السلاسل", "All Chains") else 7)
            
            m_ad = folium.Map(location=m_cent, zoom_start=zm)
            m_ad.get_root().html.add_child(folium.Element("<style>.leaflet-interactive:focus{outline:none;}</style>"))

            if not gdf_areas.empty:
                apts = gdf_areas.copy()
                def sty(nm):
                    zn = str(nm).strip().lower()
                    if zn in zvi: return zvi[zn][0]["hex"], zvi[zn][0]["hex"], 0.55, 2.2, " | ".join([f"{x['name']} ({x['vid']})" for x in zvi[zn]]), True
                    return "#3388ff", "#002266", 0.12, 1.0, T("منطقة عامة", "General"), False
                
                prs = apts["Delivery Location Area Name"].apply(sty)
                for i, k in enumerate(["fc", "bc", "fo", "wt", "ci"]): apts[k] = [p[i] for p in prs]
                
                folium.GeoJson(
                    apts[["Delivery Location Area Name", "ci", "fc", "bc", "fo", "wt", "geometry"]].to_json(),
                    style_function=lambda f: {"fillColor": f["properties"]["fc"], "color": f["properties"]["bc"], "weight": f["properties"]["wt"], "fillOpacity": f["properties"]["fo"]},
                    tooltip=folium.GeoJsonTooltip(["Delivery Location Area Name", "ci"])
                ).add_to(m_ad)

            if not pv.empty:
                mc = MarkerCluster().add_to(m_ad)
                for _, r in pv.iterrows():
                    v_str = r["clean_vid"]
                    clr = vcmap.get(v_str, {}).get("folium", "blue")
                    if s_v != T("كل الفروع", "All Vendors") and v_str == s_v:
                        folium.Marker([r["lat"], r["lng"]], popup=folium.Popup(build_popup_html(r, df_d, df_performance), max_width=320), icon=folium.Icon(color="green", icon="medkit", prefix="fa")).add_to(m_ad)
                    else:
                        folium.Marker([r["lat"], r["lng"]], popup=folium.Popup(build_popup_html(r, df_d, df_performance), max_width=320), icon=folium.Icon(color=clr, icon="medkit", prefix="fa")).add_to(mc)

            st_folium(m_ad, width="100%", height=600, returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal (إدارة مجمعة للسلاسل والأداء)
# ==========================================
with tab2:
    st.header(T("بوابة الفيندور - التغطية والتسعير", "Vendor Portal - Coverage & Pricing"))
    
    t_vid = ""
    if is_admin:
        v_inp = st.text_input(T("أدخل كود الفرع / السلسلة:", "Enter ID:")).strip()
        if v_inp:
            cid = normalize_id(v_inp)
            m_v, m_c = user_vendors[user_vendors["clean_vid"]==cid], user_vendors[user_vendors["clean_cid"]==cid]
            p_vends = m_v if not m_v.empty else (m_c if not m_c.empty else pd.DataFrame())
            if p_vends.empty: st.error("❌ الكود غير صحيح أو لا تملك صلاحية.")
    else:
        p_vends = user_vendors.copy()
        if p_vends.empty: st.warning("⚠️ لا توجد فروع مربوطة.")

    if not p_vends.empty:
        is_multi = False
        if len(p_vends) > 1:
            st.markdown("---")
            is_multi = st.toggle(T("🔄 تفعيل وضع الإدارة المجمعة لتقسيم المناطق على فروع السلسلة", "🔄 Enable Multi-Branch Allocation Mode"), False)

        if is_multi:
            st.info(T("أنت في وضع الإدارة المجمعة للسلسلة.", "Multi-Branch mode active."))
            t_vid = "MULTI"
            vd = p_vends
        else:
            opt = dict(zip(p_vends["clean_vid"], p_vends["clean_name"] + " (" + p_vends["clean_vid"] + ")"))
            t_vid = st.selectbox(T("اختر الفرع:", "Select Branch:"), list(opt.keys()), format_func=lambda x: opt[x])
            vd = p_vends[p_vends["clean_vid"]==t_vid]

        if not vd.empty:
            if is_multi:
                v_nm = T("مجموعة فروع السلسلة", "Multiple Branches")
                v_cid = vd.iloc[0]["clean_cid"]
                v_cnm = vd.iloc[0].get("clean_chain_name","")
                has_loc = pd.notna(vd["lat"]).any()
            else:
                vr = vd.iloc[0]
                t_vid = normalize_id(t_vid)
                v_nm, v_cid, v_cnm = vr["clean_name"], vr["clean_cid"], vr.get("clean_chain_name","")
                has_loc = pd.notna(vr["lat"]) and pd.notna(vr["lng"])
                st.success(f"🏬 **{v_nm}** | ID: `{t_vid}` | Chain: `{v_cid}`")
                
                # Performance display for single branch
                vp, cp = get_perf(t_vid, v_cid, df_performance)
                if vp or cp:
                    st.subheader(T("📊 الأداء", "Performance"))
                    t1, t2 = st.tabs([T("أداء الفرع", "Branch"), T("أداء السلسلة", "Chain")])
                    with t1:
                        if vp:
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Orders", vp.get("qc_orders","-"))
                            c2.metric("Failed", f"{vp.get('fail_orders','-')} ({vp.get('fail_rate','-')})")
                            c3.metric("Contact %", vp.get("contact_rate","-"))
                            c4.metric("Fault CR", vp.get("fault_cr","-"))
                    with t2:
                        if cp:
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Chain Orders", cp.get("qc_orders","-"))
                            c2.metric("Chain Failed", f"{cp.get('fail_orders','-')} ({cp.get('fail_rate','-')})")
                            c3.metric("Chain Contact %", cp.get("contact_rate","-"))
                            c4.metric("Chain Fault CR", cp.get("fault_cr","-"))

            rad = st.slider(T("نطاق الخريطة (كم):", "Radius (km):"), 3, 40, 10)
            
            if has_loc:
                if is_multi:
                    pa = gdf_areas[gdf_areas.geometry.intersects(Point(vd["lng"].mean(), vd["lat"].mean()).buffer(rad/111.0))].copy()
                else:
                    pa = get_nearby_polygons(vr["lat"], vr["lng"], rad)
            else: pa = gdf_areas.head(30) if not gdf_areas.empty else gpd.GeoDataFrame()

            az = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist()) if not gdf_areas.empty else []
            zlk = {z.strip().lower(): z for z in az}

            pf_z, pf_d = [], {}
            if not df_delivery.empty and "clean_vid" in df_delivery.columns:
                m_del = df_delivery[df_delivery["clean_vid"].isin(vd["clean_vid"])] if is_multi else df_delivery[df_delivery["clean_vid"] == t_vid]
                for _, r in m_del.iterrows():
                    zn = zlk.get(str(r.get(get_col(df_delivery, ["Area Name", "Zone"]))).strip().lower())
                    if zn:
                        if zn not in pf_z: pf_z.append(zn)
                        tc, fc = get_col(df_delivery, ["Delivery Time", "Time"]), get_col(df_delivery, ["Delivery Fees", "Fee"])
                        pf_d[zn] = {"time": str(r[tc]) if pd.notna(r[tc]) else "", "fees": float(r[fc]) if pd.notna(r[fc]) else None, "vid": str(r["clean_vid"]) if is_multi else None}

            if st.session_state.get("vp_id") != t_vid:
                st.session_state.update({"vp_id": t_vid, "ms_z": list(pf_z), "ap_z": list(pf_z), "pf_z": list(pf_z), "pf_d": pf_d, "ms_v": 0, "show_t": False})

            valid_z = [z for z in st.session_state.get("ap_z", []) if z in az]
            
            cm, cf = st.columns([6,4])
            with cm:
                st.subheader(f"🗺️ Map ({len(valid_z)})")
                mcnt = [vd["lat"].mean(), vd["lng"].mean()] if (is_multi and has_loc) else ([vr["lat"], vr["lng"]] if has_loc else [30.04, 31.23])
                vmap = folium.Map(location=mcnt, zoom_start=13 if has_loc else 11)
                if has_loc:
                    for _, rv in (vd.dropna(subset=["lat","lng"]) if is_multi else vd.iloc[[0]]).iterrows():
                        folium.Marker([rv["lat"], rv["lng"]], tooltip=rv["clean_name"], icon=folium.Icon(color="green", icon="medkit", prefix="fa")).add_to(vmap)
                
                vmap.get_root().html.add_child(folium.Element("<style>.leaflet-interactive:focus{outline:none;} path.leaflet-interactive:hover{stroke:#ffc107; stroke-width:3px;}</style>"))
                if not pa.empty:
                    folium.GeoJson(
                        pa[["Delivery Location Area Name", "geometry"]].to_json(),
                        style_function=lambda f: {"fillColor": "#28a745" if f["properties"]["Delivery Location Area Name"] in valid_z else "#3388ff", "color": "#155724" if f["properties"]["Delivery Location Area Name"] in valid_z else "#002266", "weight": 2, "fillOpacity": 0.5 if f["properties"]["Delivery Location Area Name"] in valid_z else 0.15},
                        tooltip=folium.GeoJsonTooltip(["Delivery Location Area Name"])
                    ).add_to(vmap)
                
                mcd = st_folium(vmap, width="100%", height=500, returned_objects=["last_object_clicked"])
                if mcd and mcd.get("last_object_clicked"):
                    zc = mcd["last_object_clicked"].get("properties", {}).get("Delivery Location Area Name")
                    if zc and zc in az:
                        cs = f"{zc}_{np.random.randint(100)}"
                        if cs != st.session_state.get("lc"):
                            st.session_state["lc"] = cs
                            if zc in st.session_state["ms_z"]: st.session_state["ms_z"].remove(zc)
                            else: st.session_state["ms_z"].append(zc)
                            st.session_state["ap_z"] = list(st.session_state["ms_z"])
                            st.session_state["show_t"] = False
                            st.session_state["ms_v"] += 1
                            st.rerun()
            with cf:
                st.subheader(T("📝 المناطق المحددة", "Selected Zones"))
                cz = st.multiselect("Zones:", az, default=st.session_state["ms_z"], key=f"ms_{st.session_state['ms_v']}")
                b1, b2 = st.columns(2)
                if b1.button(T("👁️ تحديث الخريطة", "Apply to Map"), use_container_width=True):
                    st.session_state.update({"ap_z": cz.copy(), "ms_z": cz.copy(), "show_t": False}); st.rerun()
                if b2.button(T("🚀 تأكيد وتسعير", "Submit Selection"), type="primary", use_container_width=True):
                    st.session_state.update({"ap_z": cz.copy(), "ms_z": cz.copy(), "show_t": True}); st.rerun()

            if st.session_state.get("show_t"):
                st.markdown("---")
                st.subheader(T("💰 جدول التسعير وتوزيع الفروع", "Pricing & Allocation Table"))
                all_rz = list(st.session_state["ap_z"]) + [z for z in st.session_state["pf_z"] if z not in st.session_state["ap_z"]]
                
                th = ",".join(sorted(all_rz)) + str(is_multi)
                if st.session_state.get("ph") != th:
                    rws = []
                    v_opts = [T("غير مخصص", "Unassigned")] + [f"{r['clean_name']} ({r['clean_vid']})" for _, r in vd.iterrows()]
                    for z in all_rz:
                        pdc = st.session_state["pf_d"].get(z, {})
                        isex = z in st.session_state["pf_z"]
                        isap = z in st.session_state["ap_z"]
                        
                        astr = T("غير مخصص", "Unassigned")
                        if is_multi and pdc.get("vid"):
                            mv = vd[vd["clean_vid"]==pdc["vid"]]
                            if not mv.empty: astr = f"{mv.iloc[0]['clean_name']} ({pdc['vid']})"
                            
                        rd = {
                            "Zone": z,
                            "Status": T("📌 مسجلة", "📌 Existing") if isex else T("✨ جديدة", "✨ New"),
                            "Action": T("نشط", "Active") if isap else T("إلغاء التفعيل", "Deactivate"),
                            "Time": pdc.get("time","") if isap else "",
                            "Fees": pdc.get("fees",None) if isap else 0.0
                        }
                        if is_multi: rd["Assigned Branch"] = astr
                        rws.append(rd)
                    st.session_state["pdf"] = pd.DataFrame(rws)
                    st.session_state["ph"] = th
                    st.session_state["vopts"] = v_opts

                ccf = {
                    "Zone": st.column_config.TextColumn("Zone", disabled=True),
                    "Status": st.column_config.TextColumn("Type", disabled=True),
                    "Action": st.column_config.SelectboxColumn("Action", options=[T("نشط", "Active"), T("إلغاء التفعيل", "Deactivate")], required=True),
                    "Time": st.column_config.TextColumn("Time"),
                    "Fees": st.column_config.NumberColumn("Fees")
                }
                if is_multi: ccf["Assigned Branch"] = st.column_config.SelectboxColumn("Assigned Branch", options=st.session_state["vopts"], required=True)

                edf = st.data_editor(st.session_state["pdf"], column_config=ccf, use_container_width=True, hide_index=True)
                
                if st.button("✅ إرسال التحديث للإدارة", type="primary"):
                    err = False
                    act = edf[edf["Action"].str.contains("Active|نشط")]
                    if act["Time"].eq("").any() or act["Fees"].isnull().any():
                        st.error("⚠️ يرجى إكمال الوقت والسعر للمناطق النشطة."); err = True
                    if is_multi and act["Assigned Branch"].str.contains("Unassigned|غير مخصص").any():
                        st.error("⚠️ يرجى تعيين فرع لكل منطقة في وضع السلسلة المجمعة."); err = True
                    if not err:
                        if is_multi:
                            for bopt in act["Assigned Branch"].unique():
                                bvid = re.search(r"\((.*?)\)", bopt).group(1)
                                bnm = bopt.split("(")[0].strip()
                                bdf = edf[edf["Assigned Branch"] == bopt].copy()
                                save_detailed_request(bvid, bnm, bdf)
                            st.success("🎉 تم الإرسال بنجاح!")
                        else:
                            save_detailed_request(t_vid, v_nm, edf)
                            st.success("🎉 تم الإرسال بنجاح!")

if is_admin:
    with tab3:
        st.header(T("📥 الطلبات", "Requests"))
        if os.path.exists(REQUESTS_FILE):
            rdf = pd.read_csv(REQUESTS_FILE)
            if not rdf.empty:
                st.dataframe(rdf)
                if st.button("حذف الطلبات"): os.remove(REQUESTS_FILE); st.rerun()
