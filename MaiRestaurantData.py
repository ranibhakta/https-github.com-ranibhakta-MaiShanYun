# app: MaiRestaurantData.py
import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="MSY Inventory Intelligence", layout="wide")
st.title("🍜 Mai Shan Yun — Inventory Intelligence")

FILE_NAME = "Restaurant Data.xlsx"       # <-- your workbook
SALES_SHEET = "Restaurant Data"          # <-- exact sheet names
INGR_SHEET  = "CSVIngrediant"
SHIP_SHEET  = "CSVShipment"

def fail(msg, exc=None):
    st.error(msg)
    if exc:
        st.exception(exc)
    st.stop()

# ---------- Cleaners ----------
def normalize_month(col):
    m = pd.to_datetime(col, errors="coerce")
    if m.isna().all():
        m = pd.to_datetime(col.astype(str) + " 1, 2025", errors="coerce")
    return m.dt.to_period("M").dt.to_timestamp()

def clean_sales(df):
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # Map common variants
    col_map = {"item name":"Item Name", "item":"Item Name", "qty":"Count", "quantity":"Count"}
    for c in list(df.columns):
        lc = c.lower()
        if lc in col_map:
            df.rename(columns={c: col_map[lc]}, inplace=True)

    if "Month" not in df.columns: fail("Sales sheet is missing a 'Month' column.")
    df["Month"] = normalize_month(df["Month"])

    df["Amount"] = (df.get("Amount", 0).astype(str)
                    .str.replace("$", "", regex=False)
                    .str.replace(",", "", regex=False))
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)

    if "Count" not in df.columns: fail("Sales sheet is missing a 'Count' column.")
    df["Count"] = pd.to_numeric(df["Count"], errors="coerce").fillna(0)
    if "Item Name" not in df.columns: fail("Sales sheet is missing an 'Item Name' column.")
    return df

def clean_ingredient_map(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    low2orig = {c.lower(): c for c in df.columns}

    def pick(*cands):
        for cand in cands:
            if cand.lower() in low2orig: return low2orig[cand.lower()]
        if any("units per item" in c.lower() for c in cands):
            for k in low2orig:
                if k.startswith("units per item"): return low2orig[k]
        return None

    item_col  = pick("Item Name","Item name","item")
    ingr_col  = pick("Ingredient","Ingrediant","Ingredients")
    units_col = pick("Units per Item","Units per item","Units_per_Item","Unit per item")

    missing = [n for n,c in {"Item Name":item_col,"Ingredient":ingr_col,"Units per Item":units_col}.items() if c is None]
    if missing:
        fail(f"Ingredient map missing columns: {missing}\nFound: {list(df.columns)}")

    df.rename(columns={item_col:"Item Name", ingr_col:"Ingredient", units_col:"Units per Item"}, inplace=True)
    for c in ["Item Name","Ingredient"]: df[c] = df[c].astype(str).str.strip()
    df = df.replace({"":np.nan}).dropna(subset=["Item Name","Ingredient"]).copy()
    df["Units per Item"] = pd.to_numeric(df["Units per Item"], errors="coerce").fillna(0.0)
    df = df.groupby(["Item Name","Ingredient"], as_index=False).agg({"Units per Item":"max"})
    return df

def clean_shipments(df):
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        lc = c.lower()
        if lc == "quantity per shipment": rename[c] = "QtyPerShipment"
        elif lc == "unit of shipment":    rename[c] = "Unit"
        elif lc == "number of shipments": rename[c] = "NumShipments"
        elif lc == "frequency":           rename[c] = "Frequency"
    if rename: df.rename(columns=rename, inplace=True)

    needed = ["Ingredient","QtyPerShipment","NumShipments"]
    miss = [c for c in needed if c not in df.columns]
    if miss: fail(f"Shipment sheet missing columns: {miss}\nFound: {list(df.columns)}")

    df["QtyPerShipment"] = pd.to_numeric(df["QtyPerShipment"], errors="coerce").fillna(0.0)
    df["NumShipments"]   = pd.to_numeric(df["NumShipments"], errors="coerce").fillna(0.0)
    df["TotalReceived"]  = df["QtyPerShipment"] * df["NumShipments"]
    f = df.get("Frequency","weekly").astype(str).str.lower().str.strip()
    factor = np.where(f.eq("weekly"),1.0, np.where(f.eq("biweekly"),0.5, np.where(f.eq("monthly"),0.25,1.0)))
    df["WeeklySupply"] = df["TotalReceived"] * factor
    if "Unit" not in df.columns: df["Unit"] = ""
    return df

# ---------- Load data ----------
st.sidebar.header("Data Source")
use_local = st.sidebar.toggle("Use local Excel (Restaurant Data.xlsx)", value=True)

def load_from_local():
    if not os.path.exists(FILE_NAME):
        fail(f"'{FILE_NAME}' not found in: {os.getcwd()}\n"
             f"Tip: put the Excel next to this .py, or disable 'Use local Excel' and upload.")
    try:
        xls = pd.ExcelFile(FILE_NAME)
    except Exception as e:
        fail("Could not open workbook. Is it closed in Excel?", e)
    try:
        sales = pd.read_excel(xls, SALES_SHEET)
        ingr  = pd.read_excel(xls, INGR_SHEET)
        ship  = pd.read_excel(xls, SHIP_SHEET)
    except Exception as e:
        fail(f"Check sheet names. Expected: '{SALES_SHEET}', '{INGR_SHEET}', '{SHIP_SHEET}'.", e)
    return sales, ingr, ship

def load_from_upload():
    wb = st.sidebar.file_uploader("Upload workbook (.xlsx) with the three sheets", type=["xlsx"])
    if not wb: st.info("Upload an Excel file to continue."); st.stop()
    try:
        xls = pd.ExcelFile(wb)
        sales = pd.read_excel(xls, SALES_SHEET)
        ingr  = pd.read_excel(xls, INGR_SHEET)
        ship  = pd.read_excel(xls, SHIP_SHEET)
    except Exception as e:
        fail(f"Upload must contain sheets: '{SALES_SHEET}', '{INGR_SHEET}', '{SHIP_SHEET}'.", e)
    return sales, ingr, ship

if use_local:
    sales_raw, ingr_raw, ship_raw = load_from_local()
else:
    sales_raw, ingr_raw, ship_raw = load_from_upload()

# Show what we actually loaded (helps kill “blank page”)
with st.expander("🔎 Debug: show loaded columns"):
    st.write("Sales columns:", list(sales_raw.columns))
    st.write("Ingredient columns:", list(ingr_raw.columns))
    st.write("Shipment columns:", list(ship_raw.columns))

# ---------- Clean ----------
sales = clean_sales(sales_raw)
ingr  = clean_ingredient_map(ingr_raw)
ship  = clean_shipments(ship_raw)

# ---------- Transform (sales -> ingredient usage) ----------
usage = (sales.merge(ingr, on="Item Name", how="left")
              .assign(IngredientUsage=lambda d: d["Count"] * d["Units per Item"])
              .dropna(subset=["Ingredient"]))
usage_by_month_ing = (usage.groupby(["Month","Ingredient"], as_index=False)
                           .agg(TotalUsed=("IngredientUsage","sum"),
                                Orders=("Count","sum")))

combined = usage_by_month_ing.merge(
    ship[["Ingredient","TotalReceived","WeeklySupply","Unit"]],
    on="Ingredient", how="left"
)

# simple forecast
combined = combined.sort_values(["Ingredient","Month"]).copy()
combined["ForecastNextMonth"] = (combined.groupby("Ingredient")["TotalUsed"]
                                 .transform(lambda s: s.rolling(3, min_periods=1).mean()))
combined["Gap_Received_vs_Used"] = combined["TotalUsed"] - combined["TotalReceived"]
combined["ReorderFlag"] = np.where(combined["ForecastNextMonth"] > combined["TotalReceived"], "Reorder Soon","OK")

# ---------- KPIs ----------
total_sales  = sales["Amount"].sum()
total_orders = sales["Count"].sum()
c1,c2,c3 = st.columns(3)
c1.metric("Total Sales ($)", f"{total_sales:,.0f}")
c2.metric("Total Orders", f"{total_orders:,.0f}")
c3.metric("Ingredients Tracked", f"{combined['Ingredient'].nunique():,}")
st.markdown("---")

# ---------- Charts ----------
col1, col2 = st.columns((2,1))
agg = combined.groupby("Ingredient", as_index=False).agg(Used=("TotalUsed","sum"),
                                                         Received=("TotalReceived","max"))

with col1:
    if not agg.empty:
        fig1 = px.bar(agg.melt(id_vars="Ingredient", value_vars=["Used","Received"],
                               var_name="Type", value_name="Qty"),
                      x="Ingredient", y="Qty", color="Type", barmode="group",
                      title="📦 Received vs Used by Ingredient")
        fig1.update_xaxes(tickangle=45)
        st.plotly_chart(fig1, use_container_width=True)
    else:
        st.info("No data to display (check filters and input).")

with col2:
    if not agg.empty:
        agg["UsageRate%"] = np.where(agg["Received"]>0, (agg["Used"]/agg["Received"])*100, np.nan)
        fig2 = px.bar(agg.sort_values("UsageRate%", ascending=False),
                      x="UsageRate%", y="Ingredient", orientation="h",
                      title="⚙️ Usage Efficiency (%)")
        st.plotly_chart(fig2, use_container_width=True)

trend = (usage_by_month_ing.groupby("Month", as_index=False)
                             .agg(TotalUsed=("TotalUsed","sum")))
if not trend.empty:
    st.plotly_chart(px.line(trend, x="Month", y="TotalUsed", markers=True,
                            title="📈 Total Ingredient Usage Over Time"),
                    use_container_width=True)

# ---------- Alerts + Download ----------
st.subheader("🚨 Reorder Alerts (3-Month MA Forecast)")
st.dataframe(combined[["Month","Ingredient","TotalUsed","TotalReceived",
                       "ForecastNextMonth","Unit","ReorderFlag"]]
             .sort_values(["ReorderFlag","Ingredient","Month"]),
             use_container_width=True)

st.download_button(
    "⬇️ Download Combined (CSV)",
    data=combined.to_csv(index=False),
    file_name="MSY_Combined.csv",
    mime="text/csv"
)
