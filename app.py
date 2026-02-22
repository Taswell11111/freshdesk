import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Support Ecosystem Pulse Check",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CONFIGURATION & CREDENTIALS ---
# Uses environment variable if deployed, otherwise falls back to the provided local key
API_KEY = os.environ.get("FD_API_KEY", "ZpmwR0SRdLvfXDiIqaf2")
DOMAIN = "ecomplete.freshdesk.com"
BASE_URL = f"https://{DOMAIN}/api/v2"

# Color Palettes
COLORS = {
    'primary': ['#3B82F6', '#6366F1', '#8B5CF6', '#06B6D4', '#EC4899', '#F59E0B'],
    'status': {'Open': '#EF4444', 'Pending/Waiting': '#F59E0B'},
    'age': {'< 1 Day': '#10B981', '1 to 2 Days': '#3B82F6', '2 to 5 Days': '#F59E0B', '5+ Days': '#EF4444'}
}

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .metric-card {
        background-color: #FFFFFF;
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border-left: 5px solid;
    }
    .metric-title { color: #6B7280; font-size: 0.875rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
    .metric-val { color: #1F2937; font-size: 2.25rem; font-weight: 700; line-height: 1.2; margin-bottom: 0.25rem; }
    .metric-sub { font-size: 0.875rem; font-weight: 500; }
    
    .step-card {
        background-color: white; padding: 20px; border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border-top: 4px solid; height: 100%;
    }
    .step-num { font-size: 2rem; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- DATA FETCHING (Cached for 5 minutes) ---
@st.cache_data(ttl=300, show_spinner=False)
def fetch_freshdesk_data():
    auth = (API_KEY, 'X')
    
    # 1. Fetch Groups
    try:
        g_res = requests.get(f"{BASE_URL}/groups", auth=auth, timeout=10)
        g_res.raise_for_status()
        groups_data = g_res.json()
        group_map = {g['id']: g['name'] for g in groups_data}
    except Exception as e:
        st.error(f"Failed to fetch groups: {str(e)}")
        return {}, []

    # 2. Fetch Active Tickets
    all_tickets = []
    page = 1
    # 2 years back to catch ALL older unresolved tickets. Format: YYYY-MM-DDTHH:MM:SSZ
    updated_since = (datetime.utcnow() - timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    while True:
        url = f"{BASE_URL}/tickets?per_page=100&page={page}&updated_since={updated_since}"
        try:
            t_res = requests.get(url, auth=auth, timeout=15)
            t_res.raise_for_status()
            page_data = t_res.json()
            
            all_tickets.extend(page_data)
            
            if len(page_data) < 100:
                break
            page += 1
        except Exception as e:
            st.error(f"Failed to fetch tickets on page {page}: {str(e)}")
            break
            
    return group_map, all_tickets

# --- DATA PROCESSING ---
def process_data(group_map, raw_tickets):
    if not raw_tickets:
        return pd.DataFrame()
        
    df = pd.DataFrame(raw_tickets)
    
    # STRICT FILTER: Keep only Open (2) and Pending/Waiting (3)
    df = df[df['status'].isin([2, 3])].copy()
    
    if df.empty:
        return df
        
    # Mapping Data
    df['group_name'] = df['group_id'].map(group_map).fillna('Unassigned')
    df['status_label'] = df['status'].map({2: 'Open', 3: 'Pending/Waiting'})
    df['type'] = df['type'].fillna('Unclassified').replace('', 'Unclassified')
    
    # Calculate Age
    df['created_at'] = pd.to_datetime(df['created_at'])
    now = pd.Timestamp.utcnow()
    df['days_old'] = (now - df['created_at']).dt.total_seconds() / 86400
    
    # Age Buckets
    def assign_bucket(days):
        if days <= 1: return '< 1 Day'
        elif days <= 2: return '1 to 2 Days'
        elif days <= 5: return '2 to 5 Days'
        else: return '5+ Days'
    df['age_bucket'] = df['days_old'].apply(assign_bucket)
    
    # Has Responded
    def check_responded(row):
        if pd.notna(row.get('agent_interactions')) and row['agent_interactions'] > 0:
            return True
        if row['status'] >= 3 or pd.notna(row.get('responder_id')):
            return True
        return False
    
    df['has_responded'] = df.apply(check_responded, axis=1)
    
    return df

# --- UI RENDERING ---
def main():
    # Header
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("<span style='background-color:#2563EB; color:white; padding: 4px 16px; border-radius: 999px; font-size: 14px; font-weight: 600; text-transform: uppercase;'>Live Active Backlog</span>", unsafe_allow_html=True)
    st.markdown("<h1 style='font-size: 3.5rem; font-weight: 800; color: #111827; margin-bottom: 10px;'>Support Ecosystem <span style='color: #2563EB;'>Pulse Check</span></h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 1.25rem; color: #4B5563; max-width: 800px; margin: 0 auto 40px auto;'>Real-time analysis of unresolved ticket volumes, aging distributions, and bottlenecks powered by Freshdesk API.</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.spinner("Fetching Live Freshdesk Data..."):
        group_map, raw_tickets = fetch_freshdesk_data()
        df = process_data(group_map, raw_tickets)

    if df.empty:
        st.warning("No active tickets found or API failed to connect. Ensure your API Key is correct.")
        return

    # Calculate KPIs
    total_tickets = len(df)
    group_counts = df['group_name'].value_counts()
    top_group = group_counts.index[0] if not group_counts.empty else "N/A"
    top_group_val = group_counts.iloc[0] if not group_counts.empty else 0
    total_open = len(df[df['status_label'] == 'Open'])
    total_critical = len(df[df['age_bucket'] == '5+ Days'])

    # KPI Row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #10B981;">
            <div class="metric-title">Total Active Volume</div>
            <div class="metric-val">{total_tickets}</div>
            <div class="metric-sub" style="color: #10B981;">Excludes Closed/Resolved</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #3B82F6;">
            <div class="metric-title">Highest Volume Group</div>
            <div class="metric-val">{top_group_val}</div>
            <div class="metric-sub" style="color: #3B82F6;">{top_group}</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #8B5CF6;">
            <div class="metric-title">Total Backlog (Open)</div>
            <div class="metric-val">{total_open}</div>
            <div class="metric-sub" style="color: #8B5CF6;">Currently requiring agent action</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #EF4444;">
            <div class="metric-title">Critical Aging</div>
            <div class="metric-val">{total_critical}</div>
            <div class="metric-sub" style="color: #EF4444;">Older than 5 days unresolved</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)

    # --- CHARTS ---
    st.markdown("### Active Volume by Group")
    colA, colB = st.columns([1, 2])
    
    top_groups = group_counts.head(6)
    with colA:
        st.markdown("This chart pulls real-time unresolved ticket distributions across your active Freshdesk groups. It identifies which team or brand is currently holding the highest operational load.")
        st.write("---")
        for group, count in top_groups.items():
            st.markdown(f"**{group}:** {count} Active")
            
    with colB:
        fig_vol = px.bar(
            x=top_groups.index, y=top_groups.values, 
            labels={'x': 'Group', 'y': 'Tickets'},
            color=top_groups.index, color_discrete_sequence=COLORS['primary']
        )
        fig_vol.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor='rgba(0,0,0,0)', yaxis_gridcolor='#E5E7EB')
        st.plotly_chart(fig_vol, use_container_width=True)

    st.markdown("---")
    
    st.markdown("### Detailed Aging Analysis by Group")
    st.markdown("This stacked analysis breaks down exactly how old the unresolved tickets are within each group. Pay close attention to the **Red (5+ Days)** and **Orange (2-5 Days)** segments to identify immediate SLA risks.")
    
    # Aggregate data for Stacked Bar
    df_top_groups = df[df['group_name'].isin(top_groups.index)]
    age_order = ['< 1 Day', '1 to 2 Days', '2 to 5 Days', '5+ Days']
    age_agg = df_top_groups.groupby(['group_name', 'age_bucket']).size().reset_index(name='count')
    
    fig_age = px.bar(
        age_agg, x='group_name', y='count', color='age_bucket',
        color_discrete_map=COLORS['age'],
        category_orders={'age_bucket': age_order, 'group_name': top_groups.index},
        labels={'group_name': '', 'count': 'Tickets', 'age_bucket': 'Age Bucket'}
    )
    fig_age.update_layout(barmode='stack', margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor='rgba(0,0,0,0)', yaxis_gridcolor='#E5E7EB')
    st.plotly_chart(fig_age, use_container_width=True)

    st.markdown("---")

    # Status and Type side by side
    col_status, col_type = st.columns(2)
    with col_status:
        st.markdown("<h4 style='text-align: center;'>Active Ticket Status Count</h4>", unsafe_allow_html=True)
        status_counts = df['status_label'].value_counts().reset_index()
        fig_status = px.pie(
            status_counts, names='status_label', values='count', hole=0.6,
            color='status_label', color_discrete_map=COLORS['status']
        )
        fig_status.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5))
        st.plotly_chart(fig_status, use_container_width=True)

    with col_type:
        st.markdown("<h4 style='text-align: center;'>Active Count by Type</h4>", unsafe_allow_html=True)
        type_counts = df['type'].value_counts().head(5).reset_index().sort_values('count', ascending=True)
        fig_type = px.bar(
            type_counts, x='count', y='type', orientation='h',
            labels={'count': 'Tickets', 'type': ''},
            color_discrete_sequence=['#6366F1']
        )
        fig_type.update_layout(margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor='rgba(0,0,0,0)', xaxis_gridcolor='#E5E7EB')
        st.plotly_chart(fig_type, use_container_width=True)

    st.markdown("---")

    # Response Meter
    st.markdown("### Agent Response Meter (Active Tickets)")
    st.markdown("Visualizing the proportion of unresolved tickets that have received an initial response from an agent versus those still awaiting action.")
    
    responded = df['has_responded'].sum()
    no_response = total_tickets - responded
    res_pct = int((responded / total_tickets) * 100) if total_tickets > 0 else 0
    no_pct = 100 - res_pct

    # Custom HTML progress bar
    st.markdown(f"""
        <div style="max-width: 800px; margin: 0 auto;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <div>
                    <div style="font-size: 24px; font-weight: bold; color: #EF4444;">{no_response}</div>
                    <div style="font-size: 12px; font-weight: bold; color: #6B7280; text-transform: uppercase;">No Response</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 24px; font-weight: bold; color: #10B981;">{responded}</div>
                    <div style="font-size: 12px; font-weight: bold; color: #6B7280; text-transform: uppercase;">Agent Responded</div>
                </div>
            </div>
            <div style="display: flex; height: 32px; border-radius: 999px; overflow: hidden; background-color: #E5E7EB;">
                <div style="width: {no_pct}%; background: linear-gradient(to right, #EF4444, #F87171); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 14px;">
                    {no_pct}%
                </div>
                <div style="width: {res_pct}%; background: linear-gradient(to right, #34D399, #10B981); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 14px;">
                    {res_pct}%
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    
    # Action Plan
    st.markdown("<h2 style='text-align: center;'>Optimization Roadmap</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="step-card" style="border-color: #3B82F6;">
            <div class="step-num">❶</div>
            <h3>Target the Tail</h3>
            <p style="color: #4B5563;">Immediately allocate agents to clear tickets in the <b>5+ Days</b> bucket identified in the aging chart above.</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="step-card" style="border-color: #8B5CF6;">
            <div class="step-num">❷</div>
            <h3>Unblock Dependencies</h3>
            <p style="color: #4B5563;">Investigate groups with high "Pending" or "Waiting" statuses. Streamline external communication (e.g., Logistics).</p>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="step-card" style="border-color: #06B6D4;">
            <div class="step-num">❸</div>
            <h3>Front-Line Deflection</h3>
            <p style="color: #4B5563;">Deploy automated responses for high-frequency queries dominating the "Type" breakdown.</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    
    # Raw Data Explorer
    st.markdown("### 🗄️ Raw Ticket Explorer")
    with st.expander("Click to view and filter specific tickets"):
        st.markdown("You can search, sort, and filter the live data below.")
        
        # Clean up dataframe for display
        display_df = df[['id', 'subject', 'status_label', 'group_name', 'type', 'days_old']].copy()
        display_df['days_old'] = display_df['days_old'].round(1)
        display_df.rename(columns={
            'id': 'Ticket ID', 'subject': 'Subject', 'status_label': 'Status',
            'group_name': 'Group', 'type': 'Type', 'days_old': 'Age (Days)'
        }, inplace=True)
        
        # Streamlit Native Interactive Dataframe
        st.dataframe(
            display_df.sort_values('Age (Days)', ascending=False), 
            use_container_width=True,
            hide_index=True,
            height=400
        )

if __name__ == "__main__":
    main()
