import streamlit as st
import pandas as pd
from datetime import datetime
import os

# Page config
st.set_page_config(page_title="Zero Theta Dashboard", layout="wide")

# Custom CSS for professional styling
st.markdown("""
    <style>
    /* Main container styling */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    /* Header styling */
    h1 {
        font-weight: 600;
        margin-bottom: 2rem;
        border-bottom: 3px solid #0068c9;
        padding-bottom: 0.5rem;
    }

    h2 {
        font-weight: 500;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }

    h3 {
        font-weight: 500;
    }

    /* Metric cards styling */
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 600;
    }

    [data-testid="stMetricLabel"] {
        font-size: 0.9rem;
        font-weight: 500;
    }

    /* Dataframe styling */
    .dataframe {
        font-size: 0.9rem;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] h2 {
        border-bottom: 2px solid #0068c9;
        padding-bottom: 0.5rem;
    }

    /* Chart styling */
    .stLineChart, .stBarChart {
        border-radius: 8px;
        padding: 1rem;
    }

    /* Remove excessive padding */
    .element-container {
        margin-bottom: 0.5rem;
    }

    /* Clean table borders */
    .stDataFrame {
        border: 1px solid #e0e0e0;
        border-radius: 4px;
    }
    </style>
""", unsafe_allow_html=True)

# Load data
@st.cache_data
def load_data():
    csv_path = os.path.join(os.path.dirname(__file__), "data", "trading_results.csv")
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['entry_time'] = pd.to_datetime(df['entry_time'], errors='coerce')

    # Handle exit_time if it exists (backwards compatibility)
    if 'exit_time' in df.columns:
        df['exit_time'] = pd.to_datetime(df['exit_time'], errors='coerce')

    # Add strategy column if it doesn't exist (for backwards compatibility)
    if 'strategy' not in df.columns:
        df['strategy'] = 'Unknown'

    # Drop rows with invalid dates
    df = df.dropna(subset=['date'])

    # Calculate profits by pairing BOT and SLD actions
    # Initialize profit column
    df['profit'] = 0.0

    # Group by trade identifiers to find BOT/SLD pairs
    trade_groups = df.groupby(['date', 'trade_type', 'symbol', 'strikes'])

    for group_key, group in trade_groups:
        # Sort by entry_time to pair trades chronologically
        group = group.sort_values('entry_time')

        # Find BOT and SLD rows in this group
        bot_rows = group[group['entry_action'] == 'BOT']
        sld_rows = group[group['entry_action'] == 'SLD']

        # Pair BOT and SLD rows in chronological order
        num_pairs = min(len(bot_rows), len(sld_rows))

        for i in range(num_pairs):
            bot_idx = bot_rows.iloc[i].name
            sld_idx = sld_rows.iloc[i].name

            bot_price = bot_rows.iloc[i]['entry_price']
            sld_price = sld_rows.iloc[i]['entry_price']

            # Calculate profit: (BOT - SLD) × 100
            profit = (bot_price - sld_price) * 100

            # Apply profit to both rows in the pair
            df.loc[bot_idx, 'profit'] = profit
            df.loc[sld_idx, 'profit'] = profit

    return df

df = load_data()

# Title
st.title("Zero Theta Dashboard")

# Check if dataframe is empty
if df.empty:
    st.warning("No trade data available. Please run data_collector.py to fetch trades from IB.")
    st.stop()

# Sidebar filters
st.sidebar.header("Filters")
date_range = st.sidebar.date_input(
    "Date Range",
    value=(df['date'].min().date(), df['date'].max().date()),
    key='date_range'
)

trade_type_filter = st.sidebar.multiselect(
    "Trade Type",
    options=df['trade_type'].unique(),
    default=df['trade_type'].unique()
)

strategy_filter = st.sidebar.multiselect(
    "Strategy",
    options=df['strategy'].unique(),
    default=df['strategy'].unique()
)

# Apply filters
filtered_df = df[
    (df['date'].dt.date >= date_range[0]) &
    (df['date'].dt.date <= date_range[1]) &
    (df['trade_type'].isin(trade_type_filter)) &
    (df['strategy'].isin(strategy_filter))
]

# Key Metrics
st.header("Performance Overview")
col1, col2, col3, col4, col5 = st.columns(5)

# For profit calculations, use only BOT rows to avoid double-counting
# (each trade pair has identical profit on both BOT and SLD rows)
bot_rows = filtered_df[filtered_df['entry_action'] == 'BOT']

with col1:
    days_traded = filtered_df['date'].dt.date.nunique()
    st.metric("Days Traded", days_traded)

with col2:
    # Count BOT rows only (one per trade pair)
    st.metric("Total Trades", len(bot_rows))

with col3:
    avg_profit = bot_rows['profit'].mean()
    st.metric("Avg Profit", f"${avg_profit:.2f}")

with col4:
    total_profit = bot_rows['profit'].sum()
    st.metric("Total Profit", f"${total_profit:.2f}")

with col5:
    if len(bot_rows) > 0:
        win_rate = (bot_rows['profit'] > 0).sum() / len(bot_rows) * 100
        st.metric("Win Rate", f"{win_rate:.1f}%")
    else:
        st.metric("Win Rate", "N/A")

# Separator
st.divider()

# Daily Summary
st.header("Daily Performance")
# Use only BOT rows to avoid double-counting profits
daily_summary = bot_rows.groupby(bot_rows['date'].dt.date).agg({
    'profit': ['sum', 'mean', 'count']
}).round(2)
daily_summary.columns = ['Total Profit', 'Avg Profit', 'Trades']
daily_summary = daily_summary.sort_index(ascending=False)
st.dataframe(daily_summary, use_container_width=True, height=300)

# Separator
st.divider()

# Charts
st.header("Analytics")
col1, col2 = st.columns(2)

with col1:
    st.subheader("Profit by Date")
    # Use only BOT rows to avoid double-counting profits
    daily_profit = bot_rows.groupby(bot_rows['date'].dt.date)['profit'].sum()
    st.line_chart(daily_profit)

with col2:
    st.subheader("Profit by Strategy")
    # Use only BOT rows to avoid double-counting profits
    strategy_profit = bot_rows.groupby('strategy')['profit'].sum()
    st.bar_chart(strategy_profit)

# Separator
st.divider()

# Detailed Trade Log
st.header("Trade Log")
display_df = filtered_df.copy()
display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
display_df['entry_time'] = display_df['entry_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
if 'exit_time' in display_df.columns:
    display_df['exit_time'] = display_df['exit_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
display_df['profit'] = display_df['profit'].apply(lambda x: f"${x:.2f}")

st.dataframe(
    display_df.sort_values('entry_time', ascending=False),
    use_container_width=True,
    hide_index=True
)
