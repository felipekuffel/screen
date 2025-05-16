import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from streamlit_javascript import st_javascript
from firebase_admin import credentials, auth as admin_auth, db
import firebase_admin
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
    plot_ativo
)



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



st.title("📌 Análise Individual de Ticker")

# Input manual do ticker
ticker_manual = st.text_input("Digite o ticker (ex: AAPL)").upper()

# Botão para acionar a análise
if st.button("🔎 Carregar") and ticker_manual:
    with st.spinner("Carregando..."):
        try:
            df = yf.download(ticker_manual, period="18mo", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            dias_breakout = 20
            threshold = 0.07

            df = calcular_indicadores(df, dias_breakout, threshold)
            vcp_detectado = detectar_vcp(df)
            nome = yf.Ticker(ticker_manual).info.get("shortName", ticker_manual)
            risco = avaliar_risco(df)
            tendencia = classificar_tendencia(df['Close'].tail(20))
            comentario = gerar_comentario(df, risco, tendencia, vcp_detectado)
            earnings_str, _, _ = get_earnings_info_detalhado(ticker_manual)

            st.subheader(f"{ticker_manual} - {nome}")
            col1, col2 = st.columns([3, 2])

            with col1:
                fig = plot_ativo(df, ticker_manual, nome, vcp_detectado)
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                st.markdown(comentario)
                st.markdown(f"📅 Resultado: {earnings_str}")
                st.markdown(f"📉 Risco: `{risco}`")

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
                    "Retração 38.2%": retracao_382,
                    "Retração 61.8%": retracao_618
                }

                for nome, valor in indicadores.items():
                    if "SMA" in nome:
                        nivel_nome = f"🟣 {nome}"
                    elif "Retração" in nome:
                        nivel_nome = f"📏 {nome}"
                    elif "Máxima" in nome:
                        nivel_nome = f"📈 {nome}"
                    elif "Mínima" in nome:
                        nivel_nome = f"📉 {nome}"
                    else:
                        nivel_nome = nome
                    niveis.append({"Nível": nivel_nome, "Valor": valor})

                niveis.append({"Nível": "💰 Preço Atual", "Valor": preco})

                df_niveis = pd.DataFrame(niveis)
                df_niveis["DistânciaReal"] = (df_niveis["Valor"] - preco) / preco
                df_niveis["Distância"] = (df_niveis["DistânciaReal"] * 100).map("{:+.2f}%".format)
                df_niveis["Valor"] = df_niveis["Valor"].map("{:.2f}".format)
                df_niveis = df_niveis.drop(columns=["DistânciaReal"])
                df_niveis = df_niveis.replace(r"^\s*$", np.nan, regex=True).dropna(how="any")
                df_niveis.set_index("Nível", inplace=True)

                styled_table = df_niveis.style.apply(highlight_niveis, axis=1)
                st.dataframe(styled_table, use_container_width=True, height=565)

                df_resultado = get_quarterly_growth_table_yfinance(ticker_manual)
                if df_resultado is not None:
                    st.markdown("📊 **Histórico Trimestral (YoY)**")
                    st.table(df_resultado)
                else:
                    st.warning("❌ Histórico de crescimento YoY não disponível.")

        except Exception as e:
            st.error(f"❌ Erro ao processar o ticker {ticker_manual}: {e}")
