import yfinance as yf
import pandas as pd
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import datetime
from streamlit_javascript import st_javascript
from firebase_admin import credentials, auth as admin_auth, db
import firebase_admin
import streamlit as st

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

def calcular_rs_rating(df_ativo, df_bench):
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
    rs_ref = 0.4 * perf_bench["63"] + 0.2 * perf_bench["126"] + 0.2 * perf_bench["189"] + 0.2 * perf_bench["252"]
    total_rs_score = (rs_stock / rs_ref) * 100

    thresholds = [
        (195.93, 99),
        (117.11, 90),
        (99.04, 70),
        (91.66, 50),
        (80.96, 30),
        (53.64, 10),
        (24.86, 1),
    ]

    for i in range(len(thresholds) - 1):
        upper, rating_upper = thresholds[i]
        lower, rating_lower = thresholds[i + 1]
        if lower <= total_rs_score < upper:
            return round(rating_lower + (rating_upper - rating_lower) * (total_rs_score - lower) / (upper - lower))

    return 99 if total_rs_score >= thresholds[0][0] else 1


def get_earnings_info_detalhado(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        calendar = ticker_obj.calendar
        if isinstance(calendar, dict) or isinstance(calendar, pd.Series):
            earnings = calendar.get("Earnings Date", None)
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
    df['linreg_close'] = df['Close'].rolling(length).apply(lambda x: np.polyfit(np.arange(length), x, 1)[1] + np.polyfit(np.arange(length), x, 1)[0] * (length - 1), raw=True)
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
    max1 = highs[-40:-20].max()
    max2 = highs[-20:].max()
    if pd.isna(max1) or pd.isna(max2) or not (max1 > max2):
        return False
    min1 = lows[-40:-20].min()
    min2 = lows[-20:].min()
    if pd.isna(min1) or pd.isna(min2) or not (min1 < min2):
        return False
    vol_ant = volumes[-40:-20].mean()
    vol_rec = volumes[-20:].mean()
    if pd.isna(vol_ant) or pd.isna(vol_rec) or not (vol_ant > vol_rec):
        return False
    range_ant = (highs[-40:-20] - lows[-40:-20]).mean()
    range_rec = (highs[-20:] - lows[-20:]).mean()
    if pd.isna(range_ant) or pd.isna(range_rec) or not (range_ant > range_rec):
        return False
    if pd.isna(sma50.iloc[-1]) or closes.iloc[-1] < sma50.iloc[-1] * 0.97:
        return False
    return True


def avaliar_risco(df):
    preco_atual = df['Close'].iloc[-1]
    suporte = df['Low'].rolling(20).min().iloc[-1]
    resistencia = df['High'].rolling(20).max().iloc[-1]
    risco = 5
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
    atr = df['TR'].rolling(14).mean().iloc[-1]
    if atr / preco_atual > 0.05:
        risco += 1
    else:
        risco -= 1
    if (preco_atual - suporte) / preco_atual > 0.05:
        risco += 1
    if (resistencia - preco_atual) / preco_atual < 0.03:
        risco += 1
    if preco_atual < df['SMA200'].iloc[-1]:
        risco += 1
    quedas = sum(df['Close'].tail(30).diff() < 0)
    if quedas >= 3:
        risco += 1
    recent_df = df.tail(30)
    media_volume = recent_df['Volume'].mean()
    dias_queda_volume_alto = recent_df[(recent_df['Close'] < recent_df['Close'].shift(1)) & (recent_df['Volume'] > media_volume)]
    if not dias_queda_volume_alto.empty:
        risco += 1
    if df['rompe_resistencia'].iloc[-1] and df['Volume'].iloc[-1] > df['Volume'].rolling(20).mean().iloc[-1]:
        risco -= 1
    if df['EMA20'].iloc[-1] > df['SMA50'].iloc[-1] > df['SMA150'].iloc[-1] > df['SMA200'].iloc[-1]:
        risco -= 1
    return int(min(max(round(risco), 1), 10))


def classificar_tendencia(close):
    x = np.arange(len(close))
    slope, _ = np.polyfit(x, close, 1)
    if slope > 0.05:
        return "Alta"
    elif slope < -0.05:
        return "Baixa"
    return "Lateral"


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


def get_earnings_info_detalhado(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        calendar = ticker_obj.calendar
        if isinstance(calendar, dict) or isinstance(calendar, pd.Series):
            earnings = calendar.get("Earnings Date", None)
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
