import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from Screener.indicators import (
    calcular_indicadores,
    detectar_vcp,
    avaliar_risco,
    classificar_tendencia,
    gerar_comentario,
    get_earnings_info_detalhado,
    calcular_pivot_points,
    get_quarterly_growth_table_yfinance,
    highlight_niveis,
    plot_ativo,
    calcular_rs_rating,
    inserir_preco_no_meio
)

import firebase_admin
from firebase_admin import db

# Inicializa Firebase Admin se ainda não foi feito
if not firebase_admin._apps:
    from firebase_admin import credentials
    cred = credentials.Certificate(dict(st.secrets["firebase_admin"]))
    firebase_admin.initialize_app(cred, {
        "databaseURL": st.secrets["databaseURL"]
    })

# --- Função carregadora do benchmark ---
@st.cache_data(ttl=3600)
def carregar_spy():
    df_spy = yf.download('^GSPC', period="18mo", interval="1d", progress=False)
    if df_spy is not None and not df_spy.empty:
        if isinstance(df_spy.columns, pd.MultiIndex):
            df_spy.columns = df_spy.columns.droplevel(1)
        return df_spy
    else:
        return None

# Verifica se o usuário está autenticado
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Você precisa estar logado para acessar esta página.")
    st.link_button("🔐 Ir para Login", "/")
    st.stop()

st.title("⭐ Favoritos Salvos")

uid = st.session_state.user["localId"]
fav_ref = db.reference(f"favoritos/{uid}")
favoritos = fav_ref.get()

if not favoritos:
    st.info("Nenhum ativo salvo como favorito ainda.")
    st.stop()

spy_df = carregar_spy()

for ticker, dados in favoritos.items():
    nome = dados.get("nome", ticker)
    comentario = dados.get("comentario", "")

    with st.container():
        st.subheader(f"{ticker} - {nome}")

        try:
            df = yf.download(ticker, period="18mo", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            df = calcular_indicadores(df)
            vcp_detectado = detectar_vcp(df)
            fig = plot_ativo(df, ticker, nome, vcp_detectado)
            st.plotly_chart(fig, use_container_width=True, key=f"plot_{ticker}_fav")

            preco = df["Close"].iloc[-1]
            risco = avaliar_risco(df)
            rs_rating = calcular_rs_rating(df, spy_df)
            earnings_str, _, _ = get_earnings_info_detalhado(ticker)
            df_resultado = get_quarterly_growth_table_yfinance(ticker)

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

            df_niveis = inserir_preco_no_meio(niveis, preco)
            styled_table = df_niveis.style.apply(highlight_niveis, axis=1)

            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown(comentario)
                st.markdown(f"📅 Resultado: {earnings_str}")
                st.markdown(f"📉 Risco: **{risco}**")
                if rs_rating:
                    st.markdown(f"💪 RS Rating: **{rs_rating}**")
                else:
                    st.markdown("💪 RS Rating: ❌ Não disponível")
                st.dataframe(styled_table, use_container_width=True)

            with col2:
                if df_resultado is not None:
                    st.markdown("📊 **Histórico Trimestral (YoY)**")
                    st.table(df_resultado)
                else:
                    st.warning("❌ Histórico de crescimento YoY não disponível.")

            col_r1, col_r2 = st.columns([1, 1])
            with col_r1:
                st.markdown("### 🗑️ Remover Favorito")
            with col_r2:
                if st.button(f"Remover {ticker}", key=f"remove_{ticker}"):
                    try:
                        db.reference(f"favoritos/{uid}/{ticker}").delete()
                        st.success(f"✅ {ticker} removido dos favoritos.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao remover favorito: {e}")

        except Exception as e:
            st.error(f"Erro ao carregar dados de {ticker}: {e}")
