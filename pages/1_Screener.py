
    #st.title("Dashboard de Análise Técnica")
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from finvizfinance.screener.overview import Overview
import plotly.graph_objects as go
import plotly.express as px
import time
from plotly.subplots import make_subplots
from datetime import timedelta, timezone
import pyrebase
import firebase_admin
from firebase_admin import credentials, auth as admin_auth, db
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.hazmat.primitives import serialization
from streamlit_autorefresh import st_autorefresh
import io
import sys
from contextlib import redirect_stdout, redirect_stderr
import re
from finvizfinance.screener.overview import Overview
import requests
import hashlib
import json
from streamlit_javascript import st_javascript
from firebase_admin import credentials, auth as admin_auth, db
import firebase_admin
import datetime
st.set_page_config(layout="wide")

# Inicializa Firebase Admin se ainda não foi inicializado
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase_admin"]))
    firebase_admin.initialize_app(cred, {
        "databaseURL": st.secrets["databaseURL"]
    })

# Tenta restaurar a sessão via cookie se não estiver logado
if "logged_in" not in st.session_state:
    cookie_str = st_javascript("document.cookie")
    token = None
    if cookie_str:
        for item in cookie_str.split(";"):
            if item.strip().startswith("idToken="):
                token = item.strip().split("=")[1]
                break

    if token:
        try:
            decoded = admin_auth.verify_id_token(token)
            user_data = {
                "localId": decoded["uid"],
                "email": decoded["email"]
            }
            st.session_state.logged_in = True
            st.session_state.user = user_data
        except Exception:
            st.warning("⚠️ Sessão inválida ou expirada. Faça login novamente.")

# Bloqueia acesso se ainda não estiver autenticado
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Você precisa estar logado para acessar esta página.")
    st.link_button("🔐 Ir para Login", "/")
    st.stop()

# Carrega filtros do Firebase para o usuário logado (após login verificado!)
# Sempre recarrega os filtros do Firebase após login
try:
    uid = st.session_state.user["localId"]
    snapshot = db.reference(f"filtros/{uid}").get()
    st.session_state.filtros_salvos = snapshot if snapshot else {}
except Exception as e:
    st.session_state.filtros_salvos = {}
    st.error(f"Erro ao carregar filtros do Firebase: {e}")


# At the VERY TOP of your script, after imports:
if st.session_state.get("reset_loader_selectbox_on_next_run", False):
    # Check if the key actually exists in session_state before trying to set it
    # This can prevent errors if the app is run fresh and the selectbox hasn't been instantiated yet.
    if "selectbox_carregar_filtro_estado" in st.session_state:
        st.session_state.selectbox_carregar_filtro_estado = "Selecione..."
    st.session_state.reset_loader_selectbox_on_next_run = False

st.markdown("""
    <style>
    [data-testid="stSidebar"]::before {
        content: "";
        display: block;
        height: 150px;
        background-image: url('https://i.ibb.co/1tCRXfWv/404aabba-df44-4fc5-9c02-04d5b56108b9.png');
        background-repeat: no-repeat;
        background-position: center center;
        background-size: contain;
        margin-bottom: 0px;
    }
    </style>
""", unsafe_allow_html=True)



st.markdown("""
    <div style="text-align: center; margin-top: -20px; margin-bottom: 20px;">
        <img src="https://i.ibb.co/1tCRXfWv/404aabba-df44-4fc5-9c02-04d5b56108b9.png" width="120">
    </div>
""", unsafe_allow_html=True)

# --- Função de earnings detalhado ---
def get_earnings_info_detalhado(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        calendar = ticker_obj.calendar

        if isinstance(calendar, dict) or isinstance(calendar, pd.Series):
            earnings = calendar.get("Earnings Date", None)

            # Se for uma lista de datas, pegamos a primeira futura
            if isinstance(earnings, list) and earnings:
                earnings = earnings[0]
            if isinstance(earnings, (pd.Timestamp, datetime.datetime, datetime.date)):
                earnings_date = pd.to_datetime(earnings).tz_localize("America/New_York") if pd.to_datetime(earnings).tzinfo is None else pd.to_datetime(earnings)
                now = pd.Timestamp.now(tz="America/New_York")
                delta = (earnings_date - now).days
                data_str = earnings_date.strftime('%d %b %Y')
                if delta >= 0:
                    return f" {data_str} (em {delta}d)", earnings_date, delta
                else:
                    return f"Último: {data_str} (há {-delta}d)", earnings_date, delta

        return "Indisponível", None, None
    except Exception as e:
        return f"Erro: {e}", None, None
    

def calcular_rs_rating(df_ativo, df_bench, ticker=None, log_ativo=False):
    df_ativo = df_ativo.sort_index().copy()
    df_bench = df_bench.sort_index().copy()

    def calc_perf(df, dias):
        if len(df) > dias:
            return df['Close'].iloc[-1] / df['Close'].iloc[-dias]
        else:
            return np.nan

    perf_ativo = {
        "63": calc_perf(df_ativo, 63),
        "126": calc_perf(df_ativo, 126),
        "189": calc_perf(df_ativo, 189),
        "252": calc_perf(df_ativo, 252),
    }

    perf_bench = {
        "63": calc_perf(df_bench, 63),
        "126": calc_perf(df_bench, 126),
        "189": calc_perf(df_bench, 189),
        "252": calc_perf(df_bench, 252),
    }

    if any(np.isnan(list(perf_ativo.values()))) or any(np.isnan(list(perf_bench.values()))):
        return None

    rs_stock = 0.4 * perf_ativo["63"] + 0.2 * perf_ativo["126"] + 0.2 * perf_ativo["189"] + 0.2 * perf_ativo["252"]
    rs_ref   = 0.4 * perf_bench["63"] + 0.2 * perf_bench["126"] + 0.2 * perf_bench["189"] + 0.2 * perf_bench["252"]
    total_rs_score = (rs_stock / rs_ref) * 100

    # Tabela de faixas baseada na curva do script original
    thresholds = [
        (198.0, 99),
        (120.0, 90),
        (100.0, 70),
        (91.5, 50),
        (81.0, 30),
        (53.5, 10),
        (25.0, 1),
    ]

    for i in range(len(thresholds) - 1):
        upper, rating_upper = thresholds[i]
        lower, rating_lower = thresholds[i + 1]
        if lower <= total_rs_score < upper:
            rating_final = round(rating_lower + (rating_upper - rating_lower) * (total_rs_score - lower) / (upper - lower))
            if log_ativo and ticker:
                print(f"Ticker: {ticker} | RS Score: {total_rs_score:.2f} → Rating: {rating_final}")
            return rating_final

    rating_final = 99 if total_rs_score >= thresholds[0][0] else 1
    if log_ativo and ticker:
        print(f"Ticker: {ticker} | RS Score: {total_rs_score:.2f} → Rating: {rating_final}")
    return rating_final



@st.cache_data(ttl=3600)
def carregar_spy():
    df_spy = yf.download('^GSPC', period="18mo", interval="1d", progress=False)
    if df_spy is not None and not df_spy.empty:
        if isinstance(df_spy.columns, pd.MultiIndex):
            df_spy.columns = df_spy.columns.droplevel(1)
        return df_spy
    else:
        return None

df_spy = carregar_spy()




def plot_ativo(df, ticker, nome_empresa, vcp_detectado=False):
    df = df.tail(150).copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df['index_str'] = df.index.strftime('%Y-%m-%d')

    df['pct_change'] = df['Close'].pct_change() * 100
    df['DataStr'] = df.index.strftime("%d %b")
    df["previousClose"] = df["Close"].shift(1)
    df["color"] = np.where(df["Close"] > df["previousClose"], "#2736e9", "#de32ae")
    df["Percentage"] = df["Volume"] * 100 / df['Volume'].sum()

    fig = make_subplots(
        rows=3, cols=1,
        row_heights=[0.6, 0.2, 0.2],
        specs=[[{"type": "xy"}], [{"type": "xy"}], [{"type": "xy"}]],
        vertical_spacing=0.02,
        shared_xaxes=True
    )

    hovertext = df.apply(lambda row: f"{row['DataStr']}<br>Open: {row['Open']:.2f}<br>High: {row['High']:.2f}<br>Low: {row['Low']:.2f}<br>Close: {row['Close']:.2f}<br>Variação: {row['pct_change']:.2f}%" if pd.notna(row['pct_change']) else row['DataStr'], axis=1)

   # Médias móveis (primeiro, para ficarem atrás)
    fig.add_trace(go.Scatter(x=df['index_str'], y=df['SMA50'], mode='lines',
                            line=dict(color='rgba(0, 153, 255, 0.42)', width=1), name='SMA50'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['index_str'], y=df['EMA20'], mode='lines',
                            line=dict(color='rgba(0,255,0,0.4)', width=1), name='EMA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['index_str'], y=df['SMA150'], mode='lines',
                            line=dict(color='rgba(255,165,0,0.4)', width=1), name='SMA150'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['index_str'], y=df['SMA200'], mode='lines',
                            line=dict(color='rgba(253, 76, 76, 0.4)', width=1), name='SMA200'), row=1, col=1)

    # OHLC (candles) por último para ficar por cima
    fig.add_trace(go.Ohlc(
        x=df['index_str'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color="#2736e9", decreasing_line_color="#de32ae", line_width=2.5,
        showlegend=False, text=hovertext, hoverinfo='text'), row=1, col=1)

    

    df_up = df[df['momentum_up']]
    df_rompe = df[df['rompe_resistencia']]
    fig.add_trace(go.Scatter(x=df_up['index_str'], y=df_up['High'] * 1.03, mode='markers', marker=dict(symbol='diamond', color='violet', size=6), name='Momentum Up'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_rompe['index_str'], y=df_rompe['High'] * 1.03, mode='markers', marker=dict(symbol='triangle-up', color='lime', size=6), name='Rompimento'), row=1, col=1)

    if vcp_detectado:
        last_index = df['index_str'].iloc[-1]
        last_price = df['Close'].iloc[-1]
        fig.add_trace(go.Scatter(x=[last_index], y=[last_price * 1.06], mode='markers', marker=dict(symbol='star-diamond', color='magenta', size=8), name='Padrão VCP', text=hovertext, hoverinfo='x+text'), row=1, col=1)

    fig.add_trace(go.Bar(x=df['index_str'], y=df['Volume'], text=df['Percentage'], marker_line_color=df['color'], marker_color=df['color'], name="Volume", texttemplate="%{text:.2f}%", hoverinfo="x+y", textfont=dict(color="white")), row=2, col=1)
    fig.add_trace(go.Bar(x=df['index_str'], y=df['momentum'], marker=dict(color=['rgba(23, 36, 131, 0.5)' if m > 0 else 'rgba(84, 14, 77, 0.50)' for m in df['momentum']], line=dict(width=0)), name='Momentum'), row=3, col=1)
    fig.update_xaxes(showticklabels=False, row=2, col=1)
    fig.update_xaxes(showticklabels=False, row=3, col=1)

    pct_text = f" ({df['pct_change'].iloc[-1]:+.2f}%)"
    fig.add_hline(y=df['Close'].iloc[-1], line=dict(color='rgba(128,128,128,0.5)', width=1, dash='dot'), row=1, col=1)
    pct_price = df['Close'].iloc[-1]

    fig.update_layout(
    xaxis=dict(type='category'),
    xaxis2=dict(type='category'),
    xaxis3=dict(type='category'),
    title=f"{ticker} - {nome_empresa} - {pct_price:.2f}{pct_text}",
    template='plotly_dark',
    height=900,
    hovermode='x unified',
    xaxis_rangeslider_visible=False,
    yaxis=dict(title='', side='right', type='linear', showgrid=False, zeroline=False),
    yaxis2=dict(side='right', showgrid=False, zeroline=False),
    yaxis3=dict(side='right', showgrid=False, zeroline=False),
    showlegend=False,  # ❌ desabilita a legenda
    bargap=0.1
)


    # --- FLAT BASE (conforme já estava implementado) ---
    zonas_flat = []
    i = 0
    while i < len(df) - 14:
        max_candles = 90
        min_candles = 14
        j = i + min_candles

        base_salva = None

        while j < len(df) and (j - i) <= max_candles:
            sub_df = df.iloc[i:j]
            high = sub_df['High'].max()
            low = sub_df['Low'].min()
            diff_pct = (high - low) / high * 100

            if diff_pct > 20:
                break

            if (j - i) >= min_candles:
                inicio = sub_df['index_str'].iloc[0]
                fim = sub_df['index_str'].iloc[-1]
                resistencia = round(high, 2)
                suporte = round(low, 2)
                duracao = j - i
                base_salva = (inicio, fim, resistencia, suporte, duracao)

            j += 1

        if base_salva:
            zonas_flat.append(base_salva)
            i = j
        else:
            i += 1

    for inicio, fim, resistencia, suporte, duracao in zonas_flat:
        fig.add_trace(go.Scatter(x=[inicio, inicio, fim, fim], y=[suporte, resistencia, resistencia, suporte], fill="toself", fillcolor="rgba(255, 255, 255, 0)", line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=[inicio, fim], y=[resistencia, resistencia], mode="lines", line=dict(color="green", width=2, dash="dot"), hoverinfo="skip", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=[inicio, fim], y=[suporte, suporte], mode="lines", line=dict(color="green", width=2, dash="dot"), hoverinfo="skip", showlegend=False), row=1, col=1)
        variacao_pct = ((resistencia - suporte) / resistencia) * 100
        fig.add_annotation(x=inicio, y=resistencia, text=f"{resistencia:.2f} | {variacao_pct:.1f}% | {duracao} d ", showarrow=False, font=dict(color="green", size=10), bgcolor="rgba(255, 255, 255, 0)", yanchor="bottom", xanchor="left")
        # Anotação inferior: suporte
        fig.add_annotation(x=inicio, y=suporte,text=f"{suporte:.2f}",showarrow=False,font=dict(color="green", size=10),bgcolor="rgba(255, 255, 255, 0)",yanchor="top", xanchor="left")

    try:
        earnings_df = yf.Ticker(ticker).quarterly_financials.T
        earnings_dates = [d.strftime('%Y-%m-%d') for d in earnings_df.index]
        print("Datas earnings:", earnings_dates)
        print("Datas no gráfico:", df['index_str'].tolist())


        for date in earnings_dates:
            if date in df['index_str'].values:
                for date in earnings_dates:
                    if date in df['index_str'].values:
                        fig.add_shape(
                            type="line",
                            x0=date, x1=date,
                            yref="paper", y0=0, y1=1,
                            line=dict(color="rgba(128,128,128,0.5)", dash="dot", width=1),
                        )
                        fig.add_annotation(
                            x=date, y=1,
                            xref="x", yref="paper",
                            text="", showarrow=False,
                            font=dict(color="rgba(128,128,128,0.5)", size=10),
                            xanchor="left"
                        )

    except Exception as e:
        print("Erro ao adicionar marcações de earnings:", e)

    return fig






# ---------------------- FUNÇÕES DE INDICADORES ----------------------

def pine_linreg(series, length):
    def linreg_last(x):
        idx = np.arange(length)
        slope, intercept = np.polyfit(idx, x, 1)
        return intercept + slope * (length - 1)
    return series.rolling(length).apply(linreg_last, raw=True)

def calcular_indicadores(df, length=20, momentum_threshold=0.07):
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df = df[(df['High'] > df['Low']) & (df['Open'] != df['Close'])]

    df['High20'] = df['High'].rolling(length).max().shift(1)
    df['Low20'] = df['Low'].rolling(length).min()
    
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['SMA50'] = df['Close'].rolling(50).mean()
    df['SMA150'] = df['Close'].rolling(150).mean()
    df['SMA200'] = df['Close'].rolling(200).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    
    centro = ((df['High20'] + df['Low20']) / 2 + df['Close'].rolling(length).mean()) / 2
    df['linreg_close'] = pine_linreg(df['Close'], length)
    df['momentum'] = df['linreg_close'] - centro
    df['momentum_up'] = (df['momentum'].shift(1) <= 0) & (df['momentum'] > momentum_threshold)
    df['rompe_resistencia'] = df['Close'] > df['High20']
    df['suporte'] = df['Low'].rolling(length).min()
    return df


def detectar_vcp(df):
    if 'Volume' not in df.columns or len(df) < 40:
        return False

    closes = df['Close']
    highs = df['High']
    lows = df['Low']
    volumes = df['Volume']
    sma50 = closes.rolling(50).mean()

    # 1. Dois pivôs descendentes
    max1 = highs[-40:-20].max()
    max2 = highs[-20:].max()
    if pd.isna(max1) or pd.isna(max2) or not (max1 > max2):
        return False

    min1 = lows[-40:-20].min()
    min2 = lows[-20:].min()
    if pd.isna(min1) or pd.isna(min2) or not (min1 < min2):
        return False

    # 2. Volume médio geral caindo
    vol_ant = volumes[-40:-20].mean()
    vol_rec = volumes[-20:].mean()
    if pd.isna(vol_ant) or pd.isna(vol_rec) or not (vol_ant > vol_rec):
        return False

    # 3. Range (amplitude) caindo
    range_ant = (highs[-40:-20] - lows[-40:-20]).mean()
    range_rec = (highs[-20:] - lows[-20:]).mean()
    if pd.isna(range_ant) or pd.isna(range_rec) or not (range_ant > range_rec):
        return False

    # 4. Preço ao menos na média de 50
    if pd.isna(sma50.iloc[-1]) or closes.iloc[-1] < sma50.iloc[-1] * 0.97:
        return False

    return True


def calcular_pivot_points(df):
    high = df['High'].iloc[-2]
    low = df['Low'].iloc[-2]
    close = df['Close'].iloc[-2]
    PP = (high + low + close) / 3
    R1 = 2 * PP - low
    S1 = 2 * PP - high
    R2 = PP + (R1 - S1)
    S2 = PP - (R1 - S1)
    R3 = high + 2 * (PP - low)
    S3 = low - 2 * (high - PP)
    return PP, [S1, S2, S3], [R1, R2, R3]

def classificar_tendencia(close):
    x = np.arange(len(close))
    slope, _ = np.polyfit(x, close, 1)
    if slope > 0.05:
        return "Alta"
    elif slope < -0.05:
        return "Baixa"
    else:
        return "Lateral"


# --- Nova função de risco aprimorada ---
def avaliar_risco(df):
    preco_atual = df['Close'].iloc[-1]
    suporte = df['Low'].rolling(20).min().iloc[-1]
    resistencia = df['High'].rolling(20).max().iloc[-1]
    risco = 5  # ponto base

    # ATR (volatilidade)
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
    atr = df['TR'].rolling(14).mean().iloc[-1]
    if atr / preco_atual > 0.05:
        risco += 1  # ativo volátil
    else:
        risco -= 1  # ativo estável

    # Distância até suporte
    if (preco_atual - suporte) / preco_atual > 0.05:
        risco += 1

    # Proximidade da resistência
    if (resistencia - preco_atual) / preco_atual < 0.03:
        risco += 1

    # Preço abaixo da média de 200
    if preco_atual < df['SMA200'].iloc[-1]:
        risco += 1

    # Quedas consecutivas nos últimos 30 dias
    closes = df['Close'].tail(30).reset_index(drop=True)
    quedas = sum(closes.diff() < 0)
    if quedas >= 3:
        risco += 1

    # Queda com volume alto nos últimos 30 dias
    recent_df = df.tail(30)
    media_volume = recent_df['Volume'].mean()
    dias_queda_volume_alto = recent_df[(recent_df['Close'] < recent_df['Close'].shift(1)) & (recent_df['Volume'] > media_volume)]
    if not dias_queda_volume_alto.empty:
        risco += 1

    # Rompimento de topo com volume alto
    if df['rompe_resistencia'].iloc[-1] and df['Volume'].iloc[-1] > df['Volume'].rolling(20).mean().iloc[-1]:
        risco -= 1

    # Médias alinhadas
    if df['EMA20'].iloc[-1] > df['SMA50'].iloc[-1] > df['SMA150'].iloc[-1] > df['SMA200'].iloc[-1]:
        risco -= 1

    return int(min(max(round(risco), 1), 10))

# --- Função de análise IA aprimorada ---
def gerar_comentario(df, risco, tendencia, vcp):
    comentario = "📊 Ativo em zona de observação técnica"

    sinais = []
    if df['momentum_up'].iloc[-1]:
        sinais.append("Momentum")
    if df['rompe_resistencia'].iloc[-1]:
        sinais.append("Rompimento")
    if vcp:
        sinais.append("Padrão VCP")

    if sinais:
        comentario += f"\n📈 Sinais técnicos: {', '.join(sinais)}"

    return comentario


def get_quarterly_growth_table_yfinance(ticker):
    ticker_obj = yf.Ticker(ticker)
    df = ticker_obj.quarterly_financials.T

    if df.empty or "Total Revenue" not in df.columns or "Net Income" not in df.columns:
        return None

    df = df[["Total Revenue", "Net Income"]].dropna()
    df.sort_index(ascending=False, inplace=True)

    rows = []
    for i in range(5):  # agora inclui 5 trimestres
        try:
            atual = df.iloc[i]
            trimestre_data = df.index[i].date()
            receita_atual = atual["Total Revenue"]
            lucro_atual = atual["Net Income"]

            receita_pct = None
            lucro_pct = None
            if i + 4 < len(df):
                receita_ant = df.iloc[i + 4]["Total Revenue"]
                lucro_ant = df.iloc[i + 4]["Net Income"]
                if receita_ant:
                    receita_pct = (receita_atual - receita_ant) / receita_ant * 100
                if lucro_ant:
                    lucro_pct = (lucro_atual - lucro_ant) / abs(lucro_ant) * 100

            margem = (lucro_atual / receita_atual) * 100 if receita_atual else None

            def fmt_pct(val):
                if val is None:
                    return ""
                emoji = " 🚀" if val > 18 else ""
                return f"{val:+.1f}%{emoji}"

            rows.append({
                "Trimestre": trimestre_data.strftime("%b %Y"),
                "Receita (B)": f"${receita_atual / 1e9:.2f}B",
                "Receita YoY": fmt_pct(receita_pct),
                "Lucro (B)": f"${lucro_atual / 1e9:.2f}B",
                "Lucro YoY": fmt_pct(lucro_pct),
                "Margem (%)": f"{margem:.1f}%" if margem is not None else ""
            })
        except Exception:
            continue

    df_final = pd.DataFrame(rows).set_index("Trimestre")
    return df_final




with st.expander("Expandir/Minimizar Filtros", expanded=True):
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("### 🔍 Screener")
        nome_filtro = st.text_input("💾 Nome do filtro personalizado", key="filtro_nome_input") # Changed key to avoid conflict if "filtro_nome" is used elsewhere in session_state

        # Initialize 'filtros_salvos' in session_state if it doesn't exist
        if "filtros_salvos" not in st.session_state:
            st.session_state.filtros_salvos = {}
        
        # Initialize 'selectbox_carregar_filtro_estado' if it's not already set (e.g., by the top-of-script reset)
        if "selectbox_carregar_filtro_estado" not in st.session_state:
            st.session_state.selectbox_carregar_filtro_estado = "Selecione..."

        if st.button("📌 Salvar filtro atual"):
            if st.session_state.filtro_nome_input:
                filtro_dict = {
                    "performance": st.session_state.get("filtro_performance", "Any"),
                    "volume": st.session_state.get("filtro_volume", "Over 300K"),
                    "sinal": st.session_state.get("filtro_sinal", "Nenhum"),
                    "highlow": st.session_state.get("filtro_highlow", "Any"),
                    "sma20": st.session_state.get("filtro_sma20", "Any"),
                    "sma50": st.session_state.get("filtro_sma50", "Any"),
                    "sma200": st.session_state.get("filtro_sma200", "Any"),
                    "ordenamento": st.session_state.get("ordenamento", False),
                    "sma200_crescente": st.session_state.get("sma200_crescente", False),
                    "mostrar_vcp": st.session_state.get("mostrar_vcp", False)
                }

                uid = st.session_state.user["localId"]  # ou como estiver salvo seu user ID
                path = f"filtros/{uid}/{st.session_state.filtro_nome_input}"

                try:
                    db.reference(path).set(filtro_dict)
                    st.success(f"Filtro '{st.session_state.filtro_nome_input}' salvo com sucesso no Firebase!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar no Firebase: {e}")
            else:
                st.warning("Por favor, insira um nome para o filtro.")

        # Load filter selectbox
        # The list of options now directly uses st.session_state.filtros_salvos
        opcao_selecionada_para_carregar = st.selectbox(
            "📂 Carregar filtro salvo",
            ["Selecione..."] + list(st.session_state.filtros_salvos.keys()),
            key="selectbox_carregar_filtro_estado" # This key is reset at the top of the script
        )

        # Logic for when a filter is selected from the dropdown for LOADING
        if opcao_selecionada_para_carregar != "Selecione...":
            # This block now only runs if the user makes a new selection,
            # because if it was processed, 'selectbox_carregar_filtro_estado'
            # would have been reset to "Selecione..." by the logic at the top of the script.
            filtro_data = st.session_state.filtros_salvos.get(opcao_selecionada_para_carregar)
            
            if filtro_data: # Check if filter_data was successfully retrieved
                st.session_state.update({
                    "filtro_performance": filtro_data["performance"],
                    "filtro_volume": filtro_data["volume"],
                    "filtro_sinal": filtro_data["sinal"],
                    "filtro_highlow": filtro_data["highlow"],
                    "filtro_sma20": filtro_data["sma20"],
                    "filtro_sma50": filtro_data["sma50"],
                    "filtro_sma200": filtro_data["sma200"],
                    "ordenamento": filtro_data.get("ordenamento", False),
                    "sma200_crescente": filtro_data.get("sma200_crescente", False),
                    "mostrar_vcp": filtro_data.get("mostrar_vcp", False)
                })
                  # 🔒 Salva o filtro carregado para permitir exclusão posterior
                st.session_state.filtro_a_excluir = opcao_selecionada_para_carregar
                st.session_state.reset_loader_selectbox_on_next_run = True
                st.rerun()

        if st.button("🗑️ Excluir filtro selecionado"):
            filtro_a_excluir = st.session_state.get("filtro_a_excluir", "Selecione...")
            if filtro_a_excluir != "Selecione..." and filtro_a_excluir in st.session_state.filtros_salvos:
                try:
                    uid = st.session_state.user["localId"]
                    db.reference(f"filtros/{uid}/{filtro_a_excluir}").delete()
                    st.session_state.filtros_salvos.pop(filtro_a_excluir, None)
                    st.success(f"Filtro '{filtro_a_excluir}' excluído!")
                    st.session_state.filtro_a_excluir = "Selecione..."
                    st.session_state.reset_loader_selectbox_on_next_run = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao excluir filtro: {e}")
            else:
                st.warning("Selecione um filtro da lista para excluir.")


        if st.button("🧹 Limpar filtros"):
            st.session_state.update({
                "filtro_performance": "Any",
                "filtro_volume": "Over 300K",
                "filtro_sinal": "Nenhum",
                "filtro_highlow": "Any",
                "filtro_sma20": "Any",
                "filtro_sma50": "Any",
                "filtro_sma200": "Any",
                "ordenamento": False,
                "sma200_crescente": False,
                "mostrar_vcp": False
                # Also reset any other state variables related to filter inputs if necessary
            })
            st.success("Filtros de tela limpos. Selecione novos valores.")
            # Signal that the "Carregar filtro salvo" selectbox should also reset to "Selecione..."
            st.session_state.reset_loader_selectbox_on_next_run = True
            st.rerun() # Rerun to reflect cleared filters and reset selectbox
    

    # Definitions for col2, col3, col4 widgets
    with col2:
        sinal = st.selectbox("🎯 Filtrar por sinal", ["Nenhum", "Momentum + Breakout", "Momentum", "Breakout"], key="filtro_sinal")
        threshold = st.slider("⚡ Limite de momentum", 0.01, 0.2, 0.07, key="threshold_momentum") # Added key
        dias_breakout = st.slider("📈 Breakout da máxima dos últimos X dias", 5, 252, 20, key="dias_breakout") # Added key
        lookback = st.slider("📊 Candles recentes analisados", 3, 10, 5, key="lookback_candles") # Added key

    with col3:
        performance = st.selectbox("📈 Performance", [ 'Any', 'Today Up', 'Today Down', 'Today -15%', 'Today -10%', 'Today -5%', 'Today +5%', 'Today +10%', 'Today +15%',
            'Week -30%', 'Week -20%', 'Week -10%', 'Week Down', 'Week Up', 'Week +10%', 'Week +20%', 'Week +30%',
            'Month -50%', 'Month -30%', 'Month -20%', 'Month -10%', 'Month Down', 'Month Up', 'Month +10%', 'Month +20%', 'Month +30%', 'Month +50%',
            'Quarter -50%', 'Quarter -30%', 'Quarter -20%', 'Quarter -10%', 'Quarter Down', 'Quarter Up', 'Quarter +10%', 'Quarter +20%', 'Quarter +30%', 'Quarter +50%',
            'Half -75%', 'Half -50%', 'Half -30%', 'Half -20%', 'Half -10%', 'Half Down', 'Half Up', 'Half +10%', 'Half +20%', 'Half +30%', 'Half +50%', 'Half +100%',
            'Year -75%', 'Year -50%', 'Year -30%', 'Year -20%', 'Year -10%', 'Year Down', 'Year Up', 'Year +10%', 'Year +20%', 'Year +30%', 'Year +50%', 'Year +100%', 'Year +200%', 'Year +300%', 'Year +500%',
            'YTD -75%', 'YTD -50%', 'YTD -30%', 'YTD -20%', 'YTD -10%', 'YTD -5%', 'YTD Down', 'YTD Up', 'YTD +5%', 'YTD +10%', 'YTD +20%', 'YTD +30%', 'YTD +50%', 'YTD +100%'], key="filtro_performance")
        change_filter = st.selectbox("📉 Variação Hoje", [ 'Any', 'Up', 'Up 1%', 'Up 2%', 'Up 3%', 'Up 4%', 'Up 5%', 'Up 6%', 'Up 7%', 'Up 8%', 'Up 9%', 'Up 10%', 'Up 15%', 'Up 20%',
            'Down', 'Down 1%', 'Down 2%', 'Down 3%', 'Down 4%', 'Down 5%', 'Down 6%', 'Down 7%', 'Down 8%', 'Down 9%', 'Down 10%', 'Down 15%', 'Down 20%'], key="change_filter") # Added key
        highlow_filter = st.selectbox("📊 52-Week High/Low", ['Any', 'New High', 'New Low', '5% or more below High', '10% or more below High', '15% or more below High',
            '20% or more below High', '30% or more below High', '40% or more below High', '50% or more below High',
            '60% or more below High', '70% or more below High', '80% or more below High', '90% or more below High',
            '0-3% below High', '0-5% below High', '0-10% below High',
            '5% or more above Low', '10% or more above Low', '15% or more above Low', '20% or more above Low',
            '30% or more above Low', '40% or more above Low', '50% or more above Low', '60% or more above Low',
            '70% or more above Low', '80% or more above Low', '90% or more above Low', '100% or more above Low',
            '120% or more above Low', '150% or more above Low', '200% or more above Low', '300% or more above Low',
            '500% or more above Low', '0-3% above Low', '0-5% above Low', '0-10% above Low'], key="filtro_highlow")
        volume_filter = st.selectbox("🔊 Volume Médio", ["Over 300K", "Over 500K", "Over 1M", "Over 5M", "Over 10M"], key="filtro_volume")

    with col4:
        sma20_filter = st.selectbox("SMA 20", ['Any', 'Price below SMA20', 'Price 10% below SMA20', 'Price 20% below SMA20', 'Price 30% below SMA20', 'Price 40% below SMA20', 'Price 50% below SMA20', 'Price above SMA20', 'Price 10% above SMA20', 'Price 20% above SMA20', 'Price 30% above SMA20', 'Price 40% above SMA20', 'Price 50% above SMA20', 'Price crossed SMA20', 'Price crossed SMA20 above', 'Price crossed SMA20 below', 'SMA20 crossed SMA50', 'SMA20 crossed SMA50 above', 'SMA20 crossed SMA50 below', 'SMA20 crossed SMA200', 'SMA20 crossed SMA200 above', 'SMA20 crossed SMA200 below', 'SMA20 above SMA50', 'SMA20 below SMA50', 'SMA20 above SMA200', 'SMA20 below SMA200'], key="filtro_sma20")
        sma50_filter = st.selectbox("SMA 50", ['Any', 'Price below SMA50', 'Price 10% below SMA50', 'Price 20% below SMA50', 'Price 30% below SMA50', 'Price 40% below SMA50', 'Price 50% below SMA50', 'Price above SMA50', 'Price 10% above SMA50', 'Price 20% above SMA50', 'Price 30% above SMA50', 'Price 40% above SMA50', 'Price 50% above SMA50', 'Price crossed SMA50', 'Price crossed SMA50 above', 'Price crossed SMA50 below', 'SMA50 crossed SMA20', 'SMA50 crossed SMA20 above', 'SMA50 crossed SMA20 below', 'SMA50 crossed SMA200', 'SMA50 crossed SMA200 above', 'SMA50 crossed SMA200 below', 'SMA50 above SMA20', 'SMA50 below SMA20', 'SMA50 above SMA200', 'SMA50 below SMA200'], key="filtro_sma50")
        sma200_filter = st.selectbox("SMA 200", ['Any', 'Price below SMA200', 'Price 10% below SMA200', 'Price 20% below SMA200', 'Price 30% below SMA200', 'Price 40% below SMA200', 'Price 50% below SMA200', 'Price 60% below SMA200', 'Price 70% below SMA200', 'Price 80% below SMA200', 'Price 90% below SMA200', 'Price above SMA200', 'Price 10% above SMA200', 'Price 20% above SMA200', 'Price 30% above SMA200', 'Price 40% above SMA200', 'Price 50% above SMA200', 'Price 60% above SMA200', 'Price 70% above SMA200', 'Price 80% above SMA200', 'Price 90% above SMA200', 'Price 100% above SMA200', 'Price crossed SMA200', 'Price crossed SMA200 above', 'Price crossed SMA200 below', 'SMA200 crossed SMA20', 'SMA200 crossed SMA20 above', 'SMA200 crossed SMA20 below', 'SMA200 crossed SMA50', 'SMA200 crossed SMA50 above', 'SMA200 crossed SMA50 below', 'SMA200 above SMA20', 'SMA200 below SMA20', 'SMA200 above SMA50', 'SMA200 below SMA50'], key="filtro_sma200")
        ordenamento_mm = st.checkbox("🖐 EMA20 > SMA50 > SMA150 > SMA200", value=st.session_state.get("ordenamento", False), key="ordenamento")
        sma200_crescente = st.checkbox("📈 SMA200 maior que há 30 dias", value=st.session_state.get("sma200_crescente", False), key="sma200_crescente")
        mostrar_vcp = st.checkbox("🔍 Mostrar apenas ativos com padrão VCP", value=st.session_state.get("mostrar_vcp", False), key="mostrar_vcp")

    executar = st.button("🔎 Iniciar Busca", type="primary")

# REMOVED: The generic rerun_filtros logic. Reruns are handled by actions directly.
# if st.session_state.get("rerun_filtros", False):
# st.session_state["rerun_filtros"] = False
# st.rerun()

# Construct filters_dict using values from st.session_state or widget variables directly
# It's good practice to ensure keys exist in st.session_state before get, or provide defaults
filters_dict = {
    "Performance": st.session_state.get("filtro_performance", "Any"), # Use .get for safety
    "Average Volume": st.session_state.get("filtro_volume", "Over 300K")
}
# Use st.session_state.get for all these, referencing the keys you used in the widgets
current_change_filter = st.session_state.get("change_filter", "Any")
if current_change_filter and current_change_filter != "Any": # Finviz might not like "Any" for "Change"
    filters_dict["Change"] = current_change_filter

current_highlow_filter = st.session_state.get("filtro_highlow", "Any")
if current_highlow_filter and current_highlow_filter != "Any":
    filters_dict["52-Week High/Low"] = current_highlow_filter

current_sma20_filter = st.session_state.get("filtro_sma20", "Any")
if current_sma20_filter and current_sma20_filter != "Any":
    filters_dict["20-Day Simple Moving Average"] = current_sma20_filter

current_sma50_filter = st.session_state.get("filtro_sma50", "Any")
if current_sma50_filter and current_sma50_filter != "Any":
    filters_dict["50-Day Simple Moving Average"] = current_sma50_filter

current_sma200_filter = st.session_state.get("filtro_sma200", "Any")
if current_sma200_filter and current_sma200_filter != "Any":
    filters_dict["200-Day Simple Moving Average"] = current_sma200_filter


filtros_aplicados_str_legivel = f"Sinal: {st.session_state.get('filtro_sinal', 'Nenhum')}, Perf.: {filters_dict.get('Performance', '')}, Volume: {filters_dict.get('Average Volume', '')}"


def inserir_preco_no_meio(niveis: list, preco: float) -> pd.DataFrame:
    df = pd.DataFrame(niveis)
    df["Valor"] = df["Valor"].map(lambda x: float(f"{x:.2f}"))
    df["DistânciaReal"] = (df["Valor"] - preco) / preco
    df["Distância"] = (df["DistânciaReal"] * 100).map("{:+.2f}%".format)
    df["Valor"] = df["Valor"].map("{:.2f}".format)
    df.drop(columns=["DistânciaReal"], inplace=True)
    df = df.dropna(how="any")

    df_temp = df.copy()
    df_temp["Valor_float"] = df_temp["Valor"].astype(float)

    inserido = False
    linhas_ordenadas = []

    for _, row in df_temp.sort_values(by="Valor_float", ascending=False).iterrows():
        if not inserido and float(row["Valor"]) < preco:
            linhas_ordenadas.append({
                "Nível": "💰 Preço Atual",
                "Valor": f"{preco:.2f}",
                "Distância": "{:+.2f}%".format(0)
            })
            inserido = True
        linhas_ordenadas.append(row[["Nível", "Valor", "Distância"]].to_dict())

    if not inserido:
        linhas_ordenadas.append({
            "Nível": "💰 Preço Atual",
            "Valor": f"{preco:.2f}",
            "Distância": "{:+.2f}%".format(0)
        })

    df_final = pd.DataFrame(linhas_ordenadas).set_index("Nível")
    return df_final




if "recarregar_tickers" in st.session_state:
    tickers = st.session_state.pop("recarregar_tickers")
    st.session_state.recomendacoes = []

    progress_recarregar = st.progress(0)
    status_text_recarregar = st.empty()

    def highlight_niveis(row):
        nivel = row.name
        if "Preço Atual" in nivel:
            return ["background-color: #fff3b0; font-weight: bold;"] * len(row)
        elif "🔺" in nivel:
            return ["color: #1f77b4; font-weight: bold;"] * len(row)
        elif "🔻" in nivel:
            return ["color: #2ca02c; font-weight: bold;"] * len(row)
        elif any(tag in nivel for tag in ["🟣", "📏", "📈", "📉"]):
            return ["color: #9467bd; font-style: italic;"] * len(row)
        return [""] * len(row)


    for i, ticker in enumerate(tickers):
        status_text_recarregar.text(f"🔁 Recarregando {ticker} ({i+1}/{len(tickers)})...")
        try:
            df = yf.download(ticker, period="18mo", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df = calcular_indicadores(df, dias_breakout, threshold)

            try:
                rs_rating = calcular_rs_rating(df, df_spy)
            except Exception as e:
                st.warning(f"{ticker} com erro no RS Rating: {e}")
                continue

            df["RS_Rating"] = rs_rating if rs_rating is not None else np.nan

            vcp_detectado = detectar_vcp(df)
            nome = yf.Ticker(ticker).info.get("shortName", ticker)
            risco = avaliar_risco(df)
            tendencia = classificar_tendencia(df['Close'].tail(20))
            comentario = gerar_comentario(df, risco, tendencia, vcp_detectado)
            earnings_str, _, _ = get_earnings_info_detalhado(ticker)

            with st.container():
                st.subheader(f"{ticker} - {nome}")
                col1, col2 = st.columns([3, 2])
                with col1:
                    with st.spinner(f"📊 Carregando gráfico de {ticker}..."):
                        fig = plot_ativo(df, ticker, nome, vcp_detectado)
                        st.plotly_chart(fig, use_container_width=True, key=f"plot_reload_{ticker}")
                with col2:
                    st.markdown(comentario)
                    st.markdown(f"📅 **Resultado:** {earnings_str}")
                    st.markdown(f"📉 Risco (1 a 10): **{risco}**")

                    rs_val = df["RS_Rating"].iloc[-1] if "RS_Rating" in df.columns else None
                    if rs_val is not None and not pd.isna(rs_val):
                        st.markdown(f"💪 RS Rating (1 a 99): **{int(rs_val)}**")
                    else:
                        st.markdown("💪 RS Rating: ❌ Não disponível")

                    preco = df["Close"].iloc[-1]

                    dist_sma20 = (preco - df["SMA20"].iloc[-1]) / preco * 100
                    dist_sma50 = (preco - df["SMA50"].iloc[-1]) / preco * 100
                    dist_sma200 = (preco - df["SMA200"].iloc[-1]) / preco * 100
                    dist_max52 = (preco - df["High"].rolling(252).max().iloc[-1]) / preco * 100
                    dist_min52 = (preco - df["Low"].rolling(252).min().iloc[-1]) / preco * 100



                    preco = df["Close"].iloc[-1]
                    PP, suportes, resistencias = calcular_pivot_points(df)
                    dists_resist = [(r, ((r - preco) / preco) * 100) for r in resistencias]
                    dists_suportes = [(s, ((s - preco) / preco) * 100) for s in suportes]

                    resist_ordenado = sorted([r for r in dists_resist if r[0] > preco], key=lambda x: x[0])[:3]
                    suporte_ordenado = sorted([s for s in dists_suportes if s[0] < preco], key=lambda x: -x[0])[:3]

                    niveis = []

                    for i, (valor, _) in enumerate(resist_ordenado):
                        niveis.append({"Nível": f"🔺 {i + 1}ª Resistência", "Valor": valor})

                    for i, (valor, _) in enumerate(suporte_ordenado):
                        niveis.append({"Nível": f"🔻 {i + 1}º Suporte", "Valor": valor})

                    swing_high = df["High"].rolling(40).max().iloc[-1]
                    swing_low = df["Low"].rolling(40).min().iloc[-1]
                    retracao_382 = swing_high - (swing_high - swing_low) * 0.382
                    retracao_618 = swing_high - (swing_high - swing_low) * 0.618

                    indicadores = {
                        "SMA 20": df["SMA20"].iloc[-1],
                        "SMA 50": df["SMA50"].iloc[-1],
                        "SMA 150": df["SMA150"].iloc[-1],
                        "SMA 200": df["SMA200"].iloc[-1],
                        "Máxima 52s": df["High"].rolling(252).max().iloc[-1],
                        "Mínima 52s": df["Low"].rolling(252).min().iloc[-1],
                        "Retração 38.2% (últ. 40d)": retracao_382,
                        "Retração 61.8% (últ. 40d)": retracao_618
                    }

                    for nome_ind, valor in indicadores.items():
                        if "SMA" in nome_ind:
                            nivel_nome = f"🟣 {nome_ind}"
                        elif "Retração" in nome_ind:
                            nivel_nome = f"📏 {nome_ind}"
                        elif "Máxima" in nome_ind:
                            nivel_nome = f"📈 {nome_ind}"
                        elif "Mínima" in nome_ind:
                            nivel_nome = f"📉 {nome_ind}"
                        else:
                            nivel_nome = nome_ind
                        niveis.append({"Nível": nivel_nome, "Valor": valor})

                    df_niveis = inserir_preco_no_meio(niveis, preco)
                    
                    def highlight_niveis(row):
                        nivel = row.name
                        if "Preço Atual" in nivel:
                            return ["background-color: #fff3b0; font-weight: bold;"] * len(row)
                        elif "🔺" in nivel:
                            return ["color: #1f77b4; font-weight: bold;"] * len(row)
                        elif "🔻" in nivel:
                            return ["color: #2ca02c; font-weight: bold;"] * len(row)
                        elif any(tag in nivel for tag in ["🟣", "📏", "📈", "📉"]):
                            return ["color: #9467bd; font-style: italic;"] * len(row)
                        return [""] * len(row)

                    styled_table = df_niveis.style.apply(highlight_niveis, axis=1)
                    st.dataframe(styled_table, use_container_width=True, height=565)
                    df_resultado = get_quarterly_growth_table_yfinance(ticker)
                    
                    
            preco = df["Close"].iloc[-1]
            dist_sma20 = (preco - df["SMA20"].iloc[-1]) / preco * 100
            dist_sma50 = (preco - df["SMA50"].iloc[-1]) / preco * 100
            dist_sma200 = (preco - df["SMA200"].iloc[-1]) / preco * 100
            dist_max52 = (preco - df["High"].rolling(252).max().iloc[-1]) / preco * 100
            dist_min52 = (preco - df["Low"].rolling(252).min().iloc[-1]) / preco * 100



            st.session_state.recomendacoes.append({
                "Ticker": ticker,
                "Empresa": nome,
                "Risco": risco,
                "Tendência": tendencia,
                "Comentário": comentario,
                "Earnings": earnings_str,
                "RS Rating": int(rs_val) if rs_val is not None and not pd.isna(rs_val) else "N/A",
                "Dist % SMA20": f"{dist_sma20:+.1f}%",
                "Dist % SMA50": f"{dist_sma50:+.1f}%",
                "Dist % SMA200": f"{dist_sma200:+.1f}%",
                "Dist % Máx52s": f"{dist_max52:+.1f}%",
                "Dist % Mín52s": f"{dist_min52:+.1f}%",
                "Filtros": filtros_aplicados_str_legivel
            })
        except Exception as e:
            st.warning(f"Erro ao recarregar {ticker}: {e}")
            progress_recarregar.progress(min((i + 1) / max(1, len(tickers)), 1.0))

    status_text_recarregar.empty()
    progress_recarregar.empty()
























if executar:
    st.session_state.recomendacoes = []

    status_text = st.empty()
    progress_bar = st.progress(0)
    f = io.StringIO()

    with redirect_stdout(f), redirect_stderr(f):
        with st.spinner("Buscando ativos..."):
            screener = Overview()
            screener.set_filter(filters_dict=filters_dict)
            tickers_df = screener.screener_view()

            if tickers_df is None or tickers_df.empty or 'Ticker' not in tickers_df.columns:
                st.warning("⚠️ Nenhum ticker retornado com os filtros selecionados.")
                st.stop()

    log_output = f.getvalue()
    matches = re.findall(r'loading page.*?\[(.*?)\].*?(\d+)/(\d+)', log_output)
    st.info(f"🔎 Filtros Aplicados: {filters_dict}")

    if matches:
        current, total = map(int, matches[-1][1:])
        percent = current / total
        progress_bar.progress(percent)
    else:
        status_text.text("✅ Ativos carregados.")

    tickers = tickers_df['Ticker'].tolist()
    st.success(f"✅ {len(tickers)} ativos carregados.")

    progress = st.progress(0)
    status_text = st.empty()

    for i, ticker in enumerate(tickers):
        status_text.text(f"🔍 Analisando {ticker} ({i+1}/{len(tickers)})...")
        try:
            df = yf.download(ticker, period="18mo", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df = calcular_indicadores(df, dias_breakout, threshold)
            try:
                df['RS_Rating'] = calcular_rs_rating(df, df_spy)
            except Exception as e:
                st.warning(f"⚠️ Erro ao calcular RS Rating para {ticker}: {e}")
                df['RS_Rating'] = np.nan

            if ordenamento_mm and not (df['EMA20'].iloc[-1] > df['SMA50'].iloc[-1] > df['SMA150'].iloc[-1] > df['SMA200'].iloc[-1]):
                continue

            if sma200_crescente and (len(df) < 30 or df['SMA200'].iloc[-1] <= df['SMA200'].iloc[-30]):
                continue

            momentum_cond = df['momentum_up'].iloc[-lookback:].any()
            breakout_cond = df['rompe_resistencia'].iloc[-lookback:].any()
            ambos_cond = momentum_cond and breakout_cond

            vcp_detectado = detectar_vcp(df)
            if mostrar_vcp and not vcp_detectado:
                continue

            match sinal:
                case "Momentum": cond = momentum_cond
                case "Breakout": cond = breakout_cond
                case "Momentum + Breakout": cond = ambos_cond
                case "Nenhum": cond = True

            if not cond:
                continue

            nome = yf.Ticker(ticker).info.get("shortName", ticker)
            risco = avaliar_risco(df)
            tendencia = classificar_tendencia(df['Close'].tail(20))
            comentario = gerar_comentario(df, risco, tendencia, vcp_detectado)
            earnings_str, _, _ = get_earnings_info_detalhado(ticker)

            with st.container():
                col1, col2 = st.columns([2,3])
                with col1:
                    st.subheader(f"{ticker} - {nome}")
                # Botão de Favoritar sem loop/rerun
                with col2: 
                    with st.form(key=f"form_fav_{ticker}"):
                        comentario_personalizado = st.text_input("📝 Comentário (opcional)", key=f"coment_{ticker}")
                        submit_fav = st.form_submit_button("⭐ Adicionar aos Favoritos {ticker}")
                        if submit_fav:
                            uid = st.session_state.user["localId"]
                            fav_ref = db.reference(f"favoritos/{uid}/{ticker}")
                            fav_ref.set({
                                "ticker": ticker,
                                "nome": nome,
                                "comentario": comentario_personalizado,
                                "adicionado_em": datetime.now().isoformat()
                            })
                            st.success(f"✅ {ticker} adicionado aos favoritos!")
                col1, col2 = st.columns([3, 2])

                with col1:
                    with st.spinner(f"📊 Carregando gráfico de {ticker}..."):
                        fig = plot_ativo(df, ticker, nome, vcp_detectado)
                        st.plotly_chart(fig, use_container_width=True, key=f"plot_{ticker}")

                with col2:
                    st.markdown(comentario)
                    st.markdown(f"📅 **Resultado:** {earnings_str}")
                    st.markdown(f"📉 **Risco:** `{risco}`")

                    rs_val = df["RS_Rating"].iloc[-1] if "RS_Rating" in df.columns else None
                    if rs_val is not None and not pd.isna(rs_val):
                        st.markdown(f"💪 RS Rating (1 a 99): **{int(rs_val)}**")
                    else:
                        st.markdown("💪 RS Rating: ❌ Não disponível")

                    preco = df["Close"].iloc[-1]
                    PP, suportes, resistencias = calcular_pivot_points(df)
                    dists_resist = [(r, ((r - preco) / preco) * 100) for r in resistencias]
                    dists_suportes = [(s, ((s - preco) / preco) * 100) for s in suportes]

                    resist_ordenado = sorted([r for r in dists_resist if r[0] > preco], key=lambda x: x[0])[:3]
                    suporte_ordenado = sorted([s for s in dists_suportes if s[0] < preco], key=lambda x: -x[0])[:3]

                    niveis = []

                    for i, (valor, _) in enumerate(resist_ordenado):
                        niveis.append({"Nível": f"🔺 {i + 1}ª Resistência", "Valor": valor})

                    for i, (valor, _) in enumerate(suporte_ordenado):
                        niveis.append({"Nível": f"🔻 {i + 1}º Suporte", "Valor": valor})

                    swing_high = df["High"].rolling(40).max().iloc[-1]
                    swing_low = df["Low"].rolling(40).min().iloc[-1]
                    retracao_382 = swing_high - (swing_high - swing_low) * 0.382
                    retracao_618 = swing_high - (swing_high - swing_low) * 0.618

                    indicadores = {
                        "SMA 20": df["SMA20"].iloc[-1],
                        "SMA 50": df["SMA50"].iloc[-1],
                        "SMA 150": df["SMA150"].iloc[-1],
                        "SMA 200": df["SMA200"].iloc[-1],
                        "Máxima 52s": df["High"].rolling(252).max().iloc[-1],
                        "Mínima 52s": df["Low"].rolling(252).min().iloc[-1],
                        "Retração 38.2% (últ. 40d)": retracao_382,
                        "Retração 61.8% (últ. 40d)": retracao_618
                    }

                    for nome_ind, valor in indicadores.items():
                        if "SMA" in nome_ind:
                            nivel_nome = f"🟣 {nome_ind}"
                        elif "Retração" in nome_ind:
                            nivel_nome = f"📏 {nome_ind}"
                        elif "Máxima" in nome_ind:
                            nivel_nome = f"📈 {nome_ind}"
                        elif "Mínima" in nome_ind:
                            nivel_nome = f"📉 {nome_ind}"
                        else:
                            nivel_nome = nome_ind
                        niveis.append({"Nível": nivel_nome, "Valor": valor})

                    df_niveis = inserir_preco_no_meio(niveis, preco)

                    def highlight_niveis(row):
                        nivel = row.name
                        if "Preço Atual" in nivel:
                            return ["background-color: #fff3b0; font-weight: bold;"] * len(row)
                        elif "🔺" in nivel:
                            return ["color: #1f77b4; font-weight: bold;"] * len(row)
                        elif "🔻" in nivel:
                            return ["color: #2ca02c; font-weight: bold;"] * len(row)
                        elif any(tag in nivel for tag in ["🟣", "📏", "📈", "📉"]):
                            return ["color: #9467bd; font-style: italic;"] * len(row)
                        return [""] * len(row)

                    styled_table = df_niveis.style.apply(highlight_niveis, axis=1)
                    st.dataframe(styled_table, use_container_width=True, height=565)

                    df_resultado = get_quarterly_growth_table_yfinance(ticker)
                    if df_resultado is not None:
                        st.markdown("📊 **Histórico Trimestral (YoY)**")
                        st.table(df_resultado)
                    else:
                        st.warning("❌ Histórico de crescimento YoY não disponível.")




            preco = df["Close"].iloc[-1]
            dist_sma20 = (preco - df["SMA20"].iloc[-1]) / preco * 100
            dist_sma50 = (preco - df["SMA50"].iloc[-1]) / preco * 100
            dist_sma200 = (preco - df["SMA200"].iloc[-1]) / preco * 100
            dist_max52 = (preco - df["High"].rolling(252).max().iloc[-1]) / preco * 100
            dist_min52 = (preco - df["Low"].rolling(252).min().iloc[-1]) / preco * 100

            st.session_state.recomendacoes.append({
                "Ticker": ticker,
                "Empresa": nome,
                "Risco": risco,
                "Tendência": tendencia,
                "Comentário": comentario,
                "Earnings": earnings_str,
                "RS Rating": int(rs_val) if rs_val is not None and not pd.isna(rs_val) else "N/A",
                "Dist % SMA20": f"{dist_sma20:+.1f}%",
                "Dist % SMA50": f"{dist_sma50:+.1f}%",
                "Dist % SMA200": f"{dist_sma200:+.1f}%",
                "Dist % Máx52s": f"{dist_max52:+.1f}%",
                "Dist % Mín52s": f"{dist_min52:+.1f}%",
                "Filtros": filtros_aplicados_str_legivel
            })

        except Exception as e:
            st.warning(f"Erro com {ticker}: {e}")

        progress.progress(min((i + 1) / len(tickers), 1.0))

    status_text.empty()
    progress.empty()

    if st.session_state.recomendacoes:
        st.subheader("📋 Tabela Final dos Ativos Selecionado")
        df_final = pd.DataFrame(st.session_state.recomendacoes).sort_values(by="Risco")
        st.dataframe(df_final, use_container_width=True)
        st.download_button("⬇️ Baixar CSV", df_final.to_csv(index=False).encode(), file_name="recomendacoes_ia.csv")

if executar:
    try:
        tickers_limpos = [r["Ticker"] for r in st.session_state.recomendacoes if "Ticker" in r]

        if not tickers_limpos:
            st.warning("⚠️ Nenhum ticker válido para salvar. Operação cancelada.")
            st.stop()

        def limpar_chave_firebase(s: str) -> str:
            return re.sub(r'[.$#\[\]/]', '_', s)

        filtros_serializaveis = {limpar_chave_firebase(str(k)): str(v) for k, v in filters_dict.items()}
        agora = datetime.now(timezone(timedelta(hours=-3)))
        timestamp = agora.strftime("%Y%m%d-%H%M")
        data_hora_legivel = agora.strftime("%d/%m %H:%M")
        filtros_aplicados_str = f"{st.session_state.get('filtro_sinal', '')} | {st.session_state.get('filtro_performance', '')} | {st.session_state.get('filtro_volume', '')}"
        hash_id = hashlib.md5(filtros_aplicados_str.encode()).hexdigest()[:8]
        nome_firebase_safe = f"{timestamp}_{hash_id}"

        uid = st.session_state.user["localId"]
        busca_ref = db.reference(f"historico_buscas/{uid}/{nome_firebase_safe}")

        payload = {
            "tickers": tickers_limpos,
            "filtros": filtros_serializaveis,
            "nome_exibicao": filtros_aplicados_str
        }

        json.dumps(payload)  # validação
        busca_ref.set(payload)
        st.success("✅ Histórico salvo com sucesso!")

    except Exception as e:
        st.error(f"❌ Erro ao salvar histórico: {e}")


with st.expander("🕓 Histórico de Buscas"):
    historico_ref = db.reference(f"historico_buscas/{uid}")
    historico = historico_ref.get()

    if historico:
        opcoes_dict = {}
        for chave, dados in historico.items():
            try:
                data_part = chave.split("_")[0]
                data_formatada = f"{data_part[6:8]}/{data_part[4:6]}/{data_part[0:4]}"
            except:
                data_formatada = "Data inválida"

            nome_exibicao = dados.get("nome_exibicao", chave)
            qtde = len(dados.get("tickers", []))
            nome_legivel = f"{data_formatada} - {nome_exibicao} ({qtde} ativo{'s' if qtde != 1 else ''})"
            opcoes_dict[nome_legivel] = chave

        opcoes_legiveis = list(opcoes_dict.keys())[::-1]
        busca_legivel_selecionada = st.selectbox("📅 Selecionar busca anterior:", opcoes_legiveis)
        busca_selecionada = opcoes_dict[busca_legivel_selecionada]

        tickers_antigos = historico[busca_selecionada]["tickers"]
        col_h1, col_h2 = st.columns([1, 1])

        with col_h1:
            if st.button("🔁 Recarregar gráficos dessa busca"):
                st.session_state.recarregar_tickers = tickers_antigos
                st.rerun()

        with col_h2:
            if st.button("🗑️ Excluir esse histórico"):
                try:
                    db.reference(f"historico_buscas/{uid}/{busca_selecionada}").delete()
                    st.success(f"🗑️ Histórico '{busca_legivel_selecionada}' excluído com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao excluir histórico: {e}")


__all__ = [
    "calcular_indicadores",
    "detectar_vcp",
    "avaliar_risco",
    "classificar_tendencia",
    "gerar_comentario",
    "get_earnings_info_detalhado",
    "calcular_pivot_points",
    "get_quarterly_growth_table_yfinance",
    "highlight_niveis",
    "plot_ativo"
]
