import streamlit as st
import pandas as pd
import numpy as np
from cryptography.hazmat.primitives import serialization
import re
from datetime import datetime, date
from firebase_admin import credentials, auth as admin_auth, db
import firebase_admin
from streamlit_javascript import st_javascript


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


user_id = st.session_state.user["localId"]
ref = db.reference(f"carteiras/{user_id}/simulacoes")
finalizadas_ref = db.reference(f"carteiras/{user_id}/simulacoes_finalizadas")
simulacoes_salvas = ref.get()

if "simulacoes" not in st.session_state:
    st.session_state.simulacoes = simulacoes_salvas if simulacoes_salvas else []
# Recalcula $ STOP e $ RISCO de todas simulações carregadas
def recalcular_riscos(sim):
    tabela_df = pd.DataFrame(sim["tabela"])
    pl_total = sim["pl_total"]
    risco_acumulado = 0.0

    for i, row in tabela_df.iterrows():
        try:
            preco = float(str(row["ADD"]).replace("$", "").replace(",", ""))
            qtd = float(str(row["QTD"]).replace(" UN", "").replace(",", ""))
            stop_pct = float(str(row["STOP"]).replace("%", "").strip())
        except:
            continue

        stop_price = preco * (1 - stop_pct / 100)
        risco_valor = (preco - stop_price) * qtd
        risco_pct_pl = -risco_valor / pl_total * 100 if pl_total else 0

        tabela_df.at[i, "$ STOP"] = f"$ {stop_price:.2f}"
        tabela_df.at[i, "$ RISCO"] = f"$ {-risco_valor:.2f}"
        tabela_df.at[i, "RISCO"] = f"{risco_pct_pl:.2f}% PL"

    sim["tabela"] = tabela_df.to_dict(orient="list")
    return sim

# Reprocessa todas simulações ao carregar
for i in range(len(st.session_state.simulacoes)):
    sim = st.session_state.simulacoes[i]
    if "tabela" in sim:
        sim = recalcular_riscos(sim)
        st.session_state.simulacoes[i] = sim


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
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)



@st.cache_data(ttl=10)
def get_preco_atual(ticker):
    import yfinance as yf
    try:
        return yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1]
    except:
        return None




def limpar_chaves_invalidas(obj, path="root"):
    if isinstance(obj, dict):
        novo = {}
        for k, v in obj.items():
            k_str = str(k)
            caminho_atual = f"{path}.{k_str}"
            if not k_str or re.search(r'[.$#[\]/]', k_str):
                continue
            novo[k_str] = limpar_chaves_invalidas(v, path=caminho_atual)
        return novo
    elif isinstance(obj, list):
        return [limpar_chaves_invalidas(item, path=f"{path}[{i}]") for i, item in enumerate(obj)]
    else:
        return obj

def registrar_venda(sim, preco_venda, qtd_vendida, data_venda):
    preco_venda = float(preco_venda)
    qtd_vendida = int(qtd_vendida)
    valor_total_venda = preco_venda * qtd_vendida

    # Calcula o custo com base nas compras reais, se houver
    if "compras_reais" in sim and sim["compras_reais"]:
        total_valor = sum([c["preco"] * c["qtd"] for c in sim["compras_reais"]])
        total_qtd = sum([c["qtd"] for c in sim["compras_reais"]])
        preco_medio = total_valor / total_qtd if total_qtd else 0
    else:
        preco_medio = sim["total_valor"] / sim["total_unidades"]

    valor_total_custo = preco_medio * qtd_vendida
    lucro = valor_total_venda - valor_total_custo
    lucro_pct = lucro / valor_total_custo * 100 if valor_total_custo else 0

    tipo = "🟡 Parcial" if qtd_vendida < sim.get("quantidade_real", sim["quantidade_restante"]) else "🔴 Total"

    venda = {
        "nome": sim["nome"],
        "data": datetime.strptime(data_venda, "%d/%m/%Y").strftime('%d/%m/%Y') if isinstance(data_venda, str) else data_venda.strftime('%d/%m/%Y'),
        "preco_venda": preco_venda,
        "quantidade": qtd_vendida,
        "lucro": lucro,
        "lucro_pct": lucro_pct,
        "tipo": tipo
    }

    # Salva venda no Firebase
    vendas_anteriores = finalizadas_ref.get() or []
    vendas_anteriores.append(venda)
    finalizadas_ref.set(limpar_chaves_invalidas(vendas_anteriores))

    # Atualiza ou remove a simulação
    if tipo == "🔴 Total":
        st.session_state.simulacoes.remove(sim)
    else:
        sim["quantidade_real"] = max(0, sim.get("quantidade_real", 0) - qtd_vendida)
        sim["quantidade_restante"] = max(0, sim.get("quantidade_restante", 0) - qtd_vendida)

    # Atualiza Firebase
    ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))

if 'edit_index' in st.session_state:
    sim = st.session_state.simulacoes[st.session_state.edit_index]
    nome_default = sim['nome']
    cotacao_default = sim['cotacao']
    venda_pct_default = sim['venda_pct']
    pl_total_default = sim['pl_total']

    # Pré-carrega valores das etapas
    try:
        for i, nome in enumerate(["COMPRA INICIAL", "COMPRA 2", "COMPRA 3"]):
            subida = float(sim["tabela"]["% PARA COMPRA"][i].replace('%', ''))
            stop = float(sim["tabela"]["STOP"][i].replace('%', ''))
            pct_pl = float(sim["tabela"]["% PL COMPRA"][i].replace('%', ''))

            st.session_state[f"subida{i}"] = subida
            st.session_state[f"stop{i}"] = stop
            st.session_state[f"pct_pl{i}"] = pct_pl
    except:
        pass

else:
    nome_default = "ACMR"
    cotacao_default = 28.87
    venda_pct_default = 17.0
    pl_total_default = 10000.0





with st.container():
    st.subheader("📈✍ Planejar Nova Compra")

expanded_planning = st.session_state.get("open_planning_expander", False)

with st.expander("Expandir/Minimizar Planejamento", expanded=expanded_planning):

    # Entradas dinâmicas com atualização imediata
    col1, col2, col3, col4, col5, col6= st.columns(6)
    with col1:
        nome_acao = st.text_input("🔹 Nome da Ação", nome_default, key="nome_acao_live")
    with col2:
        cotacao = st.number_input("💲 Cotação Inicial de Compra", value=cotacao_default, step=0.01, format="%.2f", key="cotacao_live")
    with col3:
        venda_pct = st.number_input("🎯 % de Ganho para Venda", value=venda_pct_default, step=0.1, format="%.2f", key="venda_pct_live")
        preco_alvo = st.session_state.cotacao_live * (1 + venda_pct / 100)
        st.markdown(f"💰 <span style='font-size:15px;'>Preço alvo projetado: <strong>R$ {preco_alvo:.2f}</strong></span>", unsafe_allow_html=True)

    with col4:
        pl_total = st.number_input("💼 Capital Total (PL)", value=pl_total_default, step=100.0, key="pl_total_live")
    with col5:
        data_simulacao_str = st.text_input("📅 Data (DD/MM/AAAA)", date.today().strftime('%d/%m/%Y'), key="data_simulacao_live")

        try:
            data_simulacao = datetime.strptime(data_simulacao_str, "%d/%m/%Y").date()
        except ValueError:
            st.error("⚠️ Data inválida. Use o formato DD/MM/AAAA.")
            st.stop()

    with col6:
        risco_maximo_pct = st.number_input("🔻 Risco máximo do PL (%)", value=1.0, step=0.1, key="risco_maximo_pct")

    st.markdown("---")


    compra_data = []
    for i, nome in enumerate(["COMPRA INICIAL", "COMPRA 2", "COMPRA 3"]):
        with st.container():
            st.markdown(f"""
            <div style='background-color:#e2f7d5; padding: 10px 20px; border-left: 5px solid {"#007bff" if i==0 else "#28a745" if i==1 else "#ffc107"}; border-radius: 6px; margin-top: 20px; margin-bottom: 10px;'>
                <strong>🛒 {nome}</strong>
            </div>
            """, unsafe_allow_html=True)

            col1, col2, col3 = st.columns(3)

            with col1:
                if i == 0:
                    preco_entrada = st.session_state.cotacao_live
                    st.markdown(f"🔼 <strong>Entrada:</strong> ${preco_entrada:.2f}", unsafe_allow_html=True)
                    subida = 0.0
                else:
                    subida_padrao = [0.0, 4.0, 10.0][i]
                    subida_temp = st.session_state.get(f"subida{i}", subida_padrao)
                    preco_entrada = st.session_state.cotacao_live * (1 + subida_temp / 100)
                    label_subida = f"🔼 % de Subida da compra Anterior → ${preco_entrada:.2f}"
                    subida = st.number_input(label_subida, key=f"subida{i}", value=subida_temp, step=0.1)

            with col2:
                pct_pl_padrao = [8.0, 6.0, 6.0][i]
                pct_pl_temp = st.session_state.get(f"pct_pl{i}", pct_pl_padrao)
                valor_investido = st.session_state.pl_total_live * (pct_pl_temp / 100)
                qtd_calculada = valor_investido / preco_entrada if preco_entrada else 0
                label_pl = f"📊 % do PL neste compra (Qtd: {int(qtd_calculada)} UN)"
                pct_pl = st.number_input(label_pl, key=f"pct_pl{i}", value=pct_pl_temp, step=0.1)

            with col3:
                stop_padrao = [8.0, 8.0, 10.0][i]
                stop_pct = st.session_state.get(f"stop{i}", stop_padrao)
                stop_price = preco_entrada * (1 - stop_pct / 100) if preco_entrada else 0
                label_stop = f"🛑 Stop (%) → ${stop_price:.2f}"
                stop = st.number_input(label_stop, key=f"stop{i}", value=stop_pct, step=0.1)

                # ✅ Cálculo do maior STOP permitido na compra 1 sozinha para ficar dentro de 1% do PL
                if i == 0:
                    preco1 = preco_entrada
                    pct_pl1 = st.session_state.get("pct_pl0", 8.0)
                    valor1 = st.session_state.pl_total_live * (pct_pl1 / 100)
                    qtd1 = valor1 / preco1 if preco1 else 0

                    risco_maximo_pct = st.session_state.get("risco_maximo_pct", 1.0)
                    risco_max_total = st.session_state.pl_total_live * (risco_maximo_pct / 100)

                    if qtd1 > 0:
                        stop_price_max = preco1 - (risco_max_total / qtd1)
                        stop_pct_max = (preco1 - stop_price_max) / preco1 * 100

                        st.markdown(f"""
                        <span style='font-size:15px;'>📉 Stop da <strong>COMPRA INICIAL</strong> pode ser 
                        <strong>{stop_pct_max:.2f}%</strong> (R$ {stop_price_max:.2f}) para manter risco ≤ {risco_maximo_pct:.1f}% do PL</span>
                        """, unsafe_allow_html=True)



            compra_data.append({
                "nome": nome,
                "subida_pct": subida,
                "pct_pl": pct_pl,
                "stop_pct": stop
            })

    # 🔁 Gerar tabela ao vivo com base nos dados preenchidos
    linhas = []
    cotacao = st.session_state.cotacao_live
    pl_total = st.session_state.pl_total_live

    for i, nome in enumerate(["COMPRA INICIAL", "COMPRA 2", "COMPRA 3"]):
        subida = st.session_state.get(f"subida{i}", [0.0, 4.0, 10.0][i])
        pct_pl = st.session_state.get(f"pct_pl{i}", [8.0, 6.0, 6.0][i])
        stop_pct = st.session_state.get(f"stop{i}", [8.0, 8.0, 10.0][i])

        preco = cotacao * (1 + subida / 100)
        valor = pl_total * (pct_pl / 100)
        qtd = valor / preco if preco else 0
        stop_preco = preco * (1 - stop_pct / 100)
        risco_valor = (preco - stop_preco) * qtd
        risco_pct_pl = -risco_valor / pl_total * 100 if pl_total else 0

        linhas.append([
            nome,
            f"${preco:.2f}",
            f"{subida:.2f}%" if i > 0 else "Compra Inicial",
            f"${valor:,.2f}",
            f"{pct_pl:.2f}%",
            f"{int(qtd)} UN",
            f"{stop_pct:.2f}%",
            f"$ {stop_preco:.2f}",
            f"{risco_pct_pl:.2f}% PL",
            f"$ {-risco_valor:.2f}"
        ])

    df_preview = pd.DataFrame(linhas, columns=[
        "Etapa", "ADD", "% PARA COMPRA", "COMPRA PL", "% PL COMPRA",
        "QTD", "STOP", "$ STOP", "RISCO", "$ RISCO"
    ])

    st.markdown("### 📋 Planejamento de Compras (Pré-visualização)")
    st.dataframe(df_preview, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
    # 🔍 Análise de retorno e risco (base real)
    risco_maximo_pct = st.session_state.get("risco_maximo_pct", 1.0)
    risco_max_total = pl_total * (risco_maximo_pct / 100)
    venda_pct = st.session_state.get("venda_pct_live", 17.0)

    lucro_total = 0
    total_valor = 0
    total_qtd = 0

    for i in range(3):
        subida = st.session_state.get(f"subida{i}", [0.0, 4.0, 10.0][i])
        pct_pl = st.session_state.get(f"pct_pl{i}", [8.0, 6.0, 6.0][i])

        preco = cotacao * (1 + subida / 100)
        valor = pl_total * (pct_pl / 100)
        qtd = valor / preco if preco else 0

        total_valor += valor
        total_qtd += qtd

    preco_final = cotacao * (1 + venda_pct / 100)
    lucro_total = (preco_final * total_qtd) - total_valor
    rr_ratio = lucro_total / risco_max_total if risco_max_total else 0
    pl_usado_pct = (total_valor / pl_total * 100) if pl_total else 0


    st.markdown("### 📉 Resumo da Operação")
    st.markdown(f"""
    <div style='background-color:#f9f9f9; padding: 15px; border: 2px solid #dee2e6; border-radius: 8px; font-size: 16px;'>
    <ul>
    <li>🔻 <strong>Risco máximo por operação:</strong> ${risco_max_total:,.2f} ({risco_maximo_pct:.2f}% do PL)</li>
    <li>🎯 <strong>Lucro estimado (com {venda_pct:.1f}% de alvo):</strong> ${lucro_total:,.2f}</li>
    <li>📈 <strong>R/R esperado:</strong> {rr_ratio:.2f}</li>
    <li>💼 <strong>PL usado na operação:</strong> ${total_valor:,.2f} ({pl_usado_pct:.2f}%)</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

   

# 📝 Exibe o formulário de planejamento somente quando ativado
    #if st.session_state.get("show_planning_form", False):
    with st.form("form_compras_final"):
        enviado = st.form_submit_button("📅 Confirmar Planejamento de Compras", type="primary")

        if enviado:
            st.session_state.open_planning_expander = False

            if 'edit_index' in st.session_state:
                st.session_state.keep_open_idx = st.session_state.edit_index

            preco_final = st.session_state.cotacao_live * (1 + st.session_state.venda_pct_live / 100)
            total_valor = 0
            total_unidades = 0
            linhas = []

            for i, compra in enumerate(compra_data):
                preco = st.session_state.cotacao_live * (1 + compra["subida_pct"] / 100)
                valor = st.session_state.pl_total_live * (compra["pct_pl"] / 100)
                unidades = valor / preco
                stop_preco = preco * (1 - compra["stop_pct"] / 100)
                risco_valor = (preco - stop_preco) * unidades
                risco_pct_pl = -risco_valor / st.session_state.pl_total_live * 100

                linhas.append([
                    compra["nome"],
                    f"${preco:.2f}",
                    f"{compra['subida_pct']:.2f}%" if i > 0 else "Compra Inicial",
                    f"${valor:,.2f}",
                    f'{compra["pct_pl"]:.2f}%',
                    f"{int(unidades)} UN",
                    f'{compra["stop_pct"]:.2f}%',
                    f"$ {stop_preco:.2f}",
                    f"{risco_pct_pl:.2f}% PL",
                    f"$ {-risco_valor:.2f}",
                ])

                total_valor += valor
                total_unidades += unidades

            lucro = preco_final * total_unidades - total_valor
            lucro_pct = lucro / total_valor * 100
            lpl_pct = lucro / st.session_state.pl_total_live * 100

            df_tabela = pd.DataFrame(linhas, columns=[
                "Etapa", "ADD", "% PARA COMPRA", "COMPRA PL", "% PL COMPRA",
                "QTD", "STOP", "$ STOP", "RISCO", "$ RISCO"
            ])

            preco_inicial = st.session_state.cotacao_live
            qtd_inicial = int(df_tabela["QTD"][0].replace(" UN", "")) if "QTD" in df_tabela.columns else 0
            valor_inicial = preco_inicial * qtd_inicial

            nova_simulacao = {
                "nome": st.session_state.nome_acao_live,
                "cotacao": preco_inicial,
                "venda_pct": st.session_state.venda_pct_live,
                "pl_total": st.session_state.pl_total_live,
                "data_simulacao": data_simulacao.strftime('%d/%m/%Y'),
                "preco_final": preco_final,
                "lucro": lucro,
                "lucro_pct": lucro_pct,
                "lpl_pct": lpl_pct,
                "total_valor": total_valor,
                "total_unidades": total_unidades,
                "tabela": df_tabela.to_dict(),
                "quantidade_restante": int(total_unidades),
                "risco_maximo_pct": st.session_state.get("risco_maximo_pct", 1.0),
                # REGISTRO AUTOMÁTICO DA COMPRA INICIAL
                "compras_reais": [{
                    "etapa": "Inicial",
                    "preco": preco_inicial,
                    "qtd": qtd_inicial,
                    "data": data_simulacao.strftime('%d/%m/%Y')
                }],
                "quantidade_real": qtd_inicial,
                "preco_medio": preco_inicial
            }


            if 'edit_index' in st.session_state:
                sim_antigo = st.session_state.simulacoes[st.session_state.edit_index]
                nova_simulacao["compras_reais"] = sim_antigo.get("compras_reais", [])
                nova_simulacao["quantidade_real"] = sim_antigo.get("quantidade_real", 0)
                nova_simulacao["preco_medio"] = sim_antigo.get("preco_medio", st.session_state.cotacao_live)
                st.session_state.simulacoes[st.session_state.edit_index] = nova_simulacao
                del st.session_state["edit_index"]
            else:
                st.session_state.simulacoes.append(nova_simulacao)

            ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
            st.success("✅ Simulação salva com sucesso!")
            st.rerun()


st.markdown("---")
st.subheader("📈 Operações em Aberto")

if st.button("🔄 Atualizar preços"):
    st.cache_data.clear()
    st.rerun()

for idx, sim in enumerate(st.session_state.simulacoes):
    preco_medio = sim.get("preco_medio", 0)
    preco_final = sim.get("preco_final", 0)
    valor_atual = get_preco_atual(sim["nome"]) or sim.get("preco_medio", 0)

    progresso_pct = (valor_atual / preco_medio - 1) * 100 if preco_medio else 0
    progresso_ate_meta = ((valor_atual - preco_medio) / (preco_final - preco_medio)) * 100 if (preco_final - preco_medio) else 0
    if progresso_pct < 0:
        progresso_ate_meta *= 2  # Multiplica por 2 se o lucro for negativo
    restante_para_meta = ((preco_final - valor_atual) / valor_atual) * 100 if valor_atual else 0

    cor_progresso = "#28a745" if progresso_pct >= 0 else "#dc3545"
    icone_progresso = "🔼" if progresso_pct >= 0 else "🔽"

    alerta = ""
    aviso_proxima = ""
    sinal_proxima = ""

    try:
        tabela_df = pd.DataFrame(sim["tabela"])
        preco_2_pct = float(tabela_df[tabela_df["Etapa"].str.startswith("COMPRA 2")]["% PARA COMPRA"].iloc[0].replace('%',''))
        preco_2 = sim["cotacao"] * (1 + preco_2_pct / 100)

        linha_compra3 = tabela_df[tabela_df["Etapa"].str.startswith("COMPRA 3")].iloc[0]
        preco_3 = float(str(linha_compra3["ADD"]).replace("$", "").replace(",", ""))

        if valor_atual < preco_2:
            alerta = "🟢 Em faixa da COMPRA INICIAL"
            falta_pct = (preco_2 - valor_atual) / valor_atual * 100
            aviso_proxima = f"{falta_pct:.2f}% para COMPRA 2 (R$ {preco_2:.2f})"
            sinal_proxima = "🟢"

        elif valor_atual < preco_3:
            alerta = "🟡 Em faixa da COMPRA 2"
            falta_pct = (preco_3 - valor_atual) / valor_atual * 100
            aviso_proxima = f"{falta_pct:.2f}% para COMPRA 3 (R$ {preco_3:.2f})"
            sinal_proxima = "🟡"

        else:
            acima_pct = ((valor_atual - preco_3) / preco_3) * 100
            alerta = f"🔴 Acima da COMPRA 3 em +{acima_pct:.2f}% (R$ {preco_3:.2f})"
            aviso_proxima = ""
            sinal_proxima = "🔴"

    except Exception as e:
        alerta = "⚠️ Erro ao calcular faixa de preço"
        aviso_proxima = ""
        sinal_proxima = "⚠️"
    destaque_cor = "#e6fff2"
    if valor_atual >= preco_final:
        alerta = "🎉 Preço atual ultrapassou o alvo!"
        destaque_cor = "#fff3cd"
        aviso_proxima = ""

    
        # 🔍 Etapa atual (para inline)
    etapas_executadas = [c["etapa"] for c in sim.get("compras_reais", [])]
    if "3" in etapas_executadas:
        aviso_etapa_inline = " 🟠 Realizada COMPRA 3"
    elif "2" in etapas_executadas:
        aviso_etapa_inline = " 🟡 Realizada  COMPRA 2"
    elif "Inicial" in etapas_executadas:
        aviso_etapa_inline = " 🟢 Realizada  COMPRA INICIAL"
    else:
        aviso_etapa_inline = "⚠️ Nenhuma compra real"

    expander_aberto = st.session_state.get("keep_open_idx") == idx
    with st.expander(
        f"{sinal_proxima} {sim['nome']} | Inicial: {sim['cotacao']:.2f} → Atual: {valor_atual:.2f} ({progresso_pct:.2f}% )  → {aviso_proxima}  → Alvo: {preco_final:.2f} (Falta {restante_para_meta:.1f}%) • {aviso_etapa_inline} →  • Progresso Geral: {progresso_ate_meta:.1f}%",
        expanded=expander_aberto,
    ):
        
        st.progress(max(0.0, min(progresso_ate_meta / 100, 1.0)))

       

        

        # Carrega a tabela como DataFrame
        tabela_df = pd.DataFrame(sim["tabela"])

        # Garante presença de todas colunas esperadas
        colunas_desejadas = [
            "Etapa", "ADD", "% PARA COMPRA", "COMPRA PL", "% PL COMPRA",
            "QTD", "STOP", "$ STOP", "RISCO", "$ RISCO"
        ]
        for col in colunas_desejadas:
            if col not in tabela_df.columns:
                tabela_df[col] = np.nan  # ou "" se preferir string vazia

        # Exibe a tabela com as colunas na ordem correta
        st.dataframe(tabela_df[colunas_desejadas], use_container_width=True, hide_index=True)

        risco_maximo_valor = sim["pl_total"] * (sim.get("risco_maximo_pct", 1.0) / 100)
        risco_maximo_pct = sim.get("risco_maximo_pct", 1.0)
        risco_maximo_valor = sim["pl_total"] * (risco_maximo_pct / 100)
        lucro = sim.get("lucro", 0)
        rr_ratio = lucro / risco_maximo_valor if risco_maximo_valor else 0



        compras_reais = sim.get("compras_reais", [])

        if compras_reais:
            total_disponivel = sim.get("quantidade_real", 0)
            preco_medio = sim.get("preco_medio", 0)
            total_investido = sum([c["preco"] * c["qtd"] for c in compras_reais])


        # Apresentação em 2 colunas estilizadas
        col1, col2 = st.columns(2)

        with col1:
            st.markdown(f"""
            <div style='padding: 1rem; background-color: #eef5f9; border-radius: 10px; font-size: 17px;'>
            <p><strong>Objetivos da Operação:</strong>&nbsp;&nbsp;<br>
            <strong>📦 Qtd Final:</strong> {int(sim['total_unidades'])} ações (${sim['total_valor']:.2f})<br>
            <strong>📊 Lucro:</strong> $ {lucro:.2f} ({sim['lucro_pct']:.2f}%) 
            <strong>🔻 Risco:</strong> $ {risco_maximo_valor:.2f} ({risco_maximo_pct:.2f}%) &nbsp;&nbsp;|&nbsp;&nbsp;<br>
            <strong>📈 R/R:</strong> {rr_ratio:.2f}
            </div>
            """, unsafe_allow_html=True)


        with col2:
            st.markdown(f"""
            <div style='padding: 1rem; background-color: #e2f7d5; border-radius: 10px; font-size: 17px;'>
            <p><strong>Alocação Atual:</strong>&nbsp;&nbsp;<br>
            <strong>📦 Ações disponíveis para venda:</strong>  {total_disponivel} ações<br>
            <strong>💰 Preço médio acumulado:</strong> {preco_medio:.2f}<br>
            <strong>💸 Total investido nas compras reais:</strong>  {total_investido:.2f}<br>
            </div>
            """, unsafe_allow_html=True)


        st.markdown(f"")
        col_hist, col_botoes = st.columns([2, 3])

        with col_hist:
                st.markdown("#### 📜 Histórico de Compras Reais")
                for i, c in enumerate(sim.get("compras_reais", [])):
                    with st.container():
                        col1, col2, col3 = st.columns([5, 1, 1])
                        with col1:
                            st.markdown(
                                f"🛒 **Compra {i+1} ({c.get('etapa', '?')})** | "
                                f"📅 {c['data']} • "
                                f"🔢 {c['qtd']} ações • "
                                f"💵 $ {c['preco']:.2f}"
                            )
                        with col2:
                            if st.button("🗑", key=f"excluir_compra_{sim['nome']}_{idx}_{i}"):
                                # ... (sua lógica de exclusão permanece aqui, como já implementado)
                                ...
                        with col3:
                            if st.button("✏️", key=f"editar_compra_{sim['nome']}_{idx}_{i}"):
                                st.session_state["edit_compra_idx"] = (idx, i)
                                st.rerun()

                    # Bloco de edição fora das colunas
                    if st.session_state.get("edit_compra_idx") == (idx, i):
                        with st.form(key=f"form_editar_compra_{sim['nome']}_{idx}_{i}"):
                            st.markdown("#### ✏️ Editar Compra Real")
                            novo_preco = st.number_input("💵 Novo preço", value=c["preco"], step=0.01, format="%.2f", key=f"edit_preco_{idx}_{i}")
                            nova_qtd = st.number_input("📦 Nova quantidade", value=c["qtd"], step=1, min_value=1, key=f"edit_qtd_{idx}_{i}")
                            data_padrao = datetime.strptime(c["data"], "%d/%m/%Y").date()
                            nova_data_str = st.text_input("📅 Nova data da compra (DD/MM/AAAA)", data_padrao.strftime('%d/%m/%Y'), key=f"edit_data_compra_{idx}_{i}")
                            try:
                                nova_data = datetime.strptime(nova_data_str, "%d/%m/%Y").date()
                            except ValueError:
                                st.error("⚠️ Data inválida. Use o formato DD/MM/AAAA.")
                                st.stop()
                            if st.form_submit_button("💾 Salvar edição"):
                                sim["compras_reais"][i]["preco"] = novo_preco
                                sim["compras_reais"][i]["qtd"] = nova_qtd
                                sim["compras_reais"][i]["data"] = str(nova_data)
                                # Atualizar também a tabela da simulação com os dados editados
                                etapa = c.get("etapa", "Inicial")
                                etapa_nome = "COMPRA INICIAL" if etapa == "Inicial" else f"COMPRA {etapa}"
                                tabela_df = pd.DataFrame(sim["tabela"])
                                idx_linha = tabela_df[tabela_df["Etapa"].str.startswith(etapa_nome)].index

                                if not idx_linha.empty:
                                    i_tabela = idx_linha[0]
                                    preco_real = novo_preco
                                    qtd_real = nova_qtd
                                    valor_real = preco_real * qtd_real
                                    pct_pl_real = (valor_real / sim["pl_total"]) * 100
                                    preco_inicial = sim["cotacao"]
                                    subida_pct_real = (preco_real / preco_inicial - 1) * 100

                                    try:
                                        stop_pct = float(str(tabela_df.at[i_tabela, "STOP"]).replace("%", ""))
                                    except:
                                        stop_pct = 8.0

                                    stop_price = preco_real * (1 - stop_pct / 100)

                                    # Atualiza os dados na tabela
                                    tabela_df.at[i_tabela, "Etapa"] = f"{etapa_nome} - Real"
                                    tabela_df.at[i_tabela, "ADD"] = f"${preco_real:.2f}"
                                    tabela_df.at[i_tabela, "QTD"] = f"{int(qtd_real)} UN"
                                    tabela_df.at[i_tabela, "COMPRA PL"] = f"${valor_real:,.2f}"
                                    tabela_df.at[i_tabela, "% PL COMPRA"] = f"{pct_pl_real:.2f}%"
                                    tabela_df.at[i_tabela, "% PARA COMPRA"] = f"{subida_pct_real:.2f}%"
                                    # Só altera o STOP se a etapa não for "Inicial"
                                    if etapa != "Inicial":
                                        tabela_df.at[i_tabela, "$ STOP"] = f"$ {stop_price:.2f}"
                                        tabela_df.at[i_tabela, "STOP"] = f"{stop_pct:.2f}%"


                                    sim["tabela"] = tabela_df.to_dict(orient="list")


                                total_qtd = sum([compra["qtd"] for compra in sim["compras_reais"]])
                                total_valor = sum([compra["preco"] * compra["qtd"] for compra in sim["compras_reais"]])
                                sim["quantidade_real"] = total_qtd
                                sim["preco_medio"] = total_valor / total_qtd if total_qtd else 0

                                sim = recalcular_riscos(sim)
                                st.session_state.simulacoes[idx] = sim
                                ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
                                st.session_state["keep_open_idx"] = idx
                                del st.session_state["edit_compra_idx"]
                                st.success("📝 Compra editada com sucesso!")
                                st.rerun()





        with col_botoes:
            col_ed, col_del = st.columns([1, 1])
            with col_ed:
                if st.button(f"✏️ Editar Planejamento {sim['nome']}", key=f"edit_{idx}"):
                    st.session_state.open_planning_expander = True  # <- Expander abre junto
                    st.session_state.edit_index = idx
                    st.rerun()


            with col_del:
                if st.button(f"🗑 Excluir {sim['nome']}", key=f"del_{idx}"):
                    del st.session_state.simulacoes[idx]
                    ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
                    st.success("Simulação excluída com sucesso.")
                    st.rerun()

            col_venda, col_compra = st.columns(2)

            with col_venda:
                with st.form(f"venda_form_{idx}"):
                    st.markdown("### 💰 Registrar Venda")
                    disponivel = int(sim.get("quantidade_real", sim.get("quantidade_restante", 0)))

                    data_venda_str = st.text_input("📅 Data da venda (DD/MM/AAAA)", date.today().strftime('%d/%m/%Y'), key=f"data_venda_{idx}")
                    try:
                        data_venda = datetime.strptime(data_venda_str, "%d/%m/%Y").date()
                    except ValueError:
                        st.error("⚠️ Data inválida. Use o formato DD/MM/AAAA.")
                        st.stop()
#                    st.caption(f"📅 Data selecionada: {data_venda.strftime('%d/%m/%Y')}")

                    preco_venda = st.number_input("💲 Preço de venda", step=0.01, format="%.2f", key=f"preco_venda_{idx}")
                    
                    if disponivel > 0:
                        qtd_vendida = st.number_input("🔢 Quantidade vendida", step=1, format="%d", key=f"qtd_vendida_{idx}", min_value=1, max_value=disponivel)
                        if st.form_submit_button("Confirmar Venda"):
                            registrar_venda(sim, preco_venda, qtd_vendida, data_venda.strftime('%d/%m/%Y'))
                            st.session_state["keep_open_idx"] = idx
                            st.success("✅ Venda registrada com sucesso!")
                            st.rerun()
                    else:
                        st.warning("⚠️ Nenhuma ação disponível para venda.")

                with col_compra:
                    def recalcular_riscos(sim):
                        tabela_df = pd.DataFrame(sim["tabela"])
                        pl_total = sim["pl_total"]

                        risco_acumulado = 0.0

                        for i, row in tabela_df.iterrows():
                            try:
                                preco = float(str(row["ADD"]).replace("$", "").replace(",", ""))
                                qtd = float(str(row["QTD"]).replace(" UN", "").replace(",", ""))
                                try:
                                    stop_str = str(row["STOP"]).replace("%", "").strip()
                                    stop_pct = float(stop_str) if stop_str not in ["", "None", "nan"] else 0.0
                                except:
                                    stop_pct = 0.0
                            except:
                                continue

                            stop_price = preco * (1 - stop_pct / 100)
                            risco_valor = (preco - stop_price) * qtd

                            # Risco individual
                            risco_pct_pl = -risco_valor / pl_total * 100 if pl_total else 0
                            tabela_df.at[i, "RISCO"] = f"{risco_pct_pl:.2f}% PL"
                            tabela_df.at[i, "$ RISCO"] = f"$ {-risco_valor:.2f}"

                            # Risco acumulado
                            risco_acumulado += risco_valor
                            risco_pct_pl_acum = -risco_acumulado / pl_total * 100 if pl_total else 0
                            tabela_df.at[i, "ACUM. RISCO"] = f"{risco_pct_pl_acum:.2f}% PL"

                        sim["tabela"] = tabela_df.to_dict(orient="list")
                        return sim

                    with st.form(f"form_add_compra_{idx}", clear_on_submit=True):
                        st.markdown("### ➕ Registrar Compra Real")
                        etapa = st.selectbox("Etapa da compra", ["2", "3"], key=f"etapa_compra_{idx}")
                        preco_compra = st.number_input("💵 Preço da compra", step=0.01, format="%.2f", key=f"preco_compra_{idx}")
                        qtd_compra = st.number_input("🔢 Quantidade comprada", step=1, min_value=1, key=f"qtd_compra_{idx}")
                        data_compra_str = st.text_input("📅 Data da compra (DD/MM/AAAA)", date.today().strftime('%d/%m/%Y'), key=f"data_compra_{idx}")
                        try:
                            data_compra = datetime.strptime(data_compra_str, "%d/%m/%Y").date()
                        except ValueError:
                            st.error("⚠️ Data inválida. Use o formato DD/MM/AAAA.")
                            st.stop()
 #                       st.caption(f"📅 Data selecionada: {data_compra.strftime('%d/%m/%Y')}")


                        if etapa == "2":
                            preco2 = preco_compra
                            qtd2 = qtd_compra
                            tabela_df = pd.DataFrame(sim["tabela"])
                            try:
                                stop2_pct = float(tabela_df[tabela_df["Etapa"] == "COMPRA 2"]["STOP"].values[0].replace("%", ""))
                            except:
                                stop2_pct = 8.0
                            stop2_price = preco2 * (1 - stop2_pct / 100)
                            risco2 = (preco2 - stop2_price) * qtd2
                            risco_max_total = sim["pl_total"] * (st.session_state.get("risco_maximo_pct", 1.0) / 100)
                            risco_max_inicial = risco_max_total - risco2

                            compra_inicial = next((c for c in sim.get("compras_reais", []) if c.get("etapa") == "Inicial"), None)
                            if compra_inicial:
                                preco1 = compra_inicial["preco"]
                                qtd1 = compra_inicial["qtd"]
                                if risco_max_inicial > 0:
                                    novo_stop1 = preco1 - (risco_max_inicial / qtd1)
                                    novo_stop1_pct = (preco1 - novo_stop1) / preco1 * 100
                                    tabela_df.loc[tabela_df["Etapa"] == "COMPRA INICIAL", "STOP"] = f"{novo_stop1_pct:.2f}%"
                                    sim["tabela"] = tabela_df.to_dict(orient="list")
                            st.success(f"📉 Stop da COMPRA INICIAL pode ser {novo_stop1_pct:.2f}% ({novo_stop1:.2f}) para manter risco ≤ 1% do PL")

                        if etapa == "3":
                            tabela_df = pd.DataFrame(sim["tabela"])
                            try:
                                preco1 = next((c["preco"] for c in sim["compras_reais"] if c["etapa"] == "Inicial"), None)
                                if preco1:
                                    tabela_df.loc[tabela_df["Etapa"] == "COMPRA INICIAL", "STOP"] = f"{0:.2f}%"
                            except:
                                pass
                            try:
                                preco2 = next((c["preco"] for c in sim["compras_reais"] if c["etapa"] == "2"), None)
                                if preco2:
                                    tabela_df.loc[tabela_df["Etapa"] == "COMPRA 2", "STOP"] = f"{0:.2f}%"
                            except:
                                pass
                            sim["tabela"] = tabela_df.to_dict(orient="list")
                            st.success("🟢 Stops das COMPRA INICIAL e COMPRA 2 ajustados para breakeven após COMPRA 3.")

                        if st.form_submit_button("Registrar Compra"):
                            nova_compra = {
                                "etapa": etapa,
                                "preco": preco_compra,
                                "qtd": qtd_compra,
                                "data": data_compra.strftime('%d/%m/%Y')
                            }
                            if "compras_reais" not in sim:
                                sim["compras_reais"] = []
                            sim["compras_reais"].append(nova_compra)

                            etapa_nome = f"COMPRA {etapa}"
                            tabela_df = pd.DataFrame(sim["tabela"])
                            idx_linha = tabela_df[tabela_df["Etapa"] == etapa_nome].index

                            if not idx_linha.empty:
                                i = idx_linha[0]
                                preco_real = preco_compra
                                qtd_real = qtd_compra
                                valor_real = preco_real * qtd_real
                                pct_pl_real = (valor_real / sim["pl_total"]) * 100
                                preco_inicial = sim["cotacao"]
                                subida_pct_real = (preco_real / preco_inicial - 1) * 100

                                try:
                                    stop_pct_original = float(str(tabela_df.at[i, "STOP"]).replace("%", ""))
                                except:
                                    stop_pct_original = 8.0

                                novo_stop_price = preco_real * (1 - stop_pct_original / 100)

                                # ✅ Atualiza todos os campos da linha da tabela
                                tabela_df.at[i, "Etapa"] = f"{etapa_nome} - Real"
                                tabela_df.at[i, "ADD"] = f"${preco_real:.2f}"
                                tabela_df.at[i, "QTD"] = f"{int(qtd_real)} UN"
                                tabela_df.at[i, "COMPRA PL"] = f"${valor_real:,.2f}"
                                tabela_df.at[i, "% PL COMPRA"] = f"{pct_pl_real:.2f}%"
                                tabela_df.at[i, "% PARA COMPRA"] = f"{subida_pct_real:.2f}%"
                                tabela_df.at[i, "$ STOP"] = f"$ {novo_stop_price:.2f}"
                                tabela_df.at[i, "STOP"] = f"{stop_pct_original:.2f}%"

                                sim["tabela"] = tabela_df.to_dict(orient="list")

                            # Atualiza totais e risco
                            total_qtd = sum([c["qtd"] for c in sim["compras_reais"]])
                            total_valor = sum([c["preco"] * c["qtd"] for c in sim["compras_reais"]])
                            sim["quantidade_real"] = total_qtd
                            sim["preco_medio"] = total_valor / total_qtd if total_qtd else 0

                            sim = recalcular_riscos(sim)

                            st.session_state.simulacoes[idx] = sim
                            ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
                            st.session_state["keep_open_idx"] = idx
                            st.rerun()


# ✅ Limpeza após o loop
if "keep_open_idx" in st.session_state:
    del st.session_state["keep_open_idx"]






# 🔍 Painel Ampliado com Visual Alternativo
#st.markdown("---")
#st.subheader("📊 Indicadores Consolidado das Simulações")

lucro_estimado_total = sum([sim.get("lucro", 0) for sim in st.session_state.simulacoes])
total_risco_compras_reais = 0.0
total_pct_pl_executado = 0.0
total_pct_pl_planejado = 0.0

for sim in st.session_state.simulacoes:
    pl_total = sim["pl_total"]
    tabela_df = pd.DataFrame(sim["tabela"])

    # Risco e % executado
    for compra in sim.get("compras_reais", []):
        preco = compra["preco"]
        qtd = compra["qtd"]
        etapa = compra["etapa"]
        etapa_nome = f"COMPRA {etapa}" if etapa in ["2", "3"] else "COMPRA INICIAL"
        try:
            linha = tabela_df[tabela_df["Etapa"] == etapa_nome].iloc[0]
            stop_pct = float(str(linha["STOP"]).replace("%", ""))
        except:
            stop_pct = 8.0
        stop_price = preco * (1 - stop_pct / 100)
        risco = (preco - stop_price) * qtd
        total_risco_compras_reais += risco
        total_pct_pl_executado += (preco * qtd) / pl_total * 100

    # Soma das % PL COMPRA da tabela
    try:
        total_pct_pl_planejado += sum([
            float(str(p).replace("%", "")) for p in tabela_df["% PL COMPRA"]
        ])
    except:
        pass


rr_ratio = lucro_estimado_total / total_risco_compras_reais if total_risco_compras_reais else 0
qtd_simulacoes = len(st.session_state.simulacoes)


# Inicializa valores acumulados
valor_investido_total = 0
valor_mercado_total = 0

for sim in st.session_state.simulacoes:
    qtd_real = sim.get("quantidade_real", 0)
    preco_medio = sim.get("preco_medio", 0)
    valor_investido = preco_medio * qtd_real
    valor_atual = get_preco_atual(sim["nome"]) or preco_medio
    valor_mercado = valor_atual * qtd_real

    valor_investido_total += valor_investido
    valor_mercado_total += valor_mercado

# Lucro/prejuízo real até o momento
lucro_real = valor_mercado_total - valor_investido_total

# Recalcula faixa com base no risco planejado e lucro estimado
lucro_estimado_total = sum([sim.get("lucro", 0) for sim in st.session_state.simulacoes])
risco_total = total_risco_compras_reais

faixa_total = risco_total + lucro_estimado_total
if faixa_total == 0:
    faixa_total = 1

# Calcula posição relativa atual entre -risco e +lucro
progresso_pct = faixa_total / lucro_real
posicao = 49 + progresso_pct
posicao_pct = max(2, min(98, posicao))

# Determina cor e sinal
cor_valor = "#28a745" if lucro_real >= 0 else "#dc3545"
sinal = "+" if lucro_real >= 0 else "-"

# Recalcula faixa com base no risco planejado e lucro estimado
lucro_estimado_total = sum([sim.get("lucro", 0) for sim in st.session_state.simulacoes])
total_risco_compras_reais = 0.0  # Renomeado para maior clareza
for sim in st.session_state.simulacoes:
    pl_total = sim["pl_total"]
    tabela_df = pd.DataFrame(sim["tabela"])
    for compra in sim.get("compras_reais", []):
        preco = compra["preco"]
        qtd = compra["qtd"]
        etapa = compra["etapa"]
        etapa_nome = f"COMPRA {etapa}" if etapa in ["2", "3"] else "COMPRA INICIAL"
        try:
            linha = tabela_df[tabela_df["Etapa"] == etapa_nome].iloc[0]
            stop_pct = float(str(linha["STOP"]).replace("%", ""))
        except:
            stop_pct = 8.0
        stop_price = preco * (1 - stop_pct / 100)
        risco = (preco - stop_price) * qtd
        total_risco_compras_reais += risco

faixa_total = total_risco_compras_reais + lucro_estimado_total
if faixa_total == 0:
    faixa_total = 1

# Calcula a posição percentual do lucro real na faixa total
posicao_pct = ((total_risco_compras_reais + lucro_real) / (2 * faixa_total)) * 100
posicao_pct = max(0, min(100, posicao_pct))

# Determina cor e sinal
cor_valor = "#28a745" if lucro_real >= 0 else "#dc3545"
sinal = "+" if lucro_real >= 0 else "-"














# Recalcula faixa com base no risco planejado e lucro estimado
lucro_estimado_total = sum([sim.get("lucro", 0) for sim in st.session_state.simulacoes])
total_risco_compras_reais = 0.0
total_risco_operacao = 0.0  # Novo: Risco total planejado

for sim in st.session_state.simulacoes:
    pl_total = sim["pl_total"]
    tabela_df = pd.DataFrame(sim["tabela"])

    # Risco das compras REAIS
    for compra in sim.get("compras_reais", []):
        preco = compra["preco"]
        qtd = compra["qtd"]
        etapa = compra["etapa"]
        etapa_nome = f"COMPRA {etapa}" if etapa in ["2", "3"] else "COMPRA INICIAL"
        try:
            linha = tabela_df[tabela_df["Etapa"] == etapa_nome + " - Real"].iloc[0]  # Busca a linha "Real"
            stop_pct = float(str(linha["STOP"]).replace("%", ""))
        except:
            stop_pct = float(str(tabela_df[tabela_df["Etapa"] == etapa_nome]["STOP"].values[0]).replace("%", ""))
        stop_price = preco * (1 - stop_pct / 100)
        risco = (preco - stop_price) * qtd
        total_risco_compras_reais += risco

    # Risco total da OPERAÇÃO (planejado)
    for i in range(len(tabela_df)):
        try:
            preco_str = str(tabela_df.loc[i, "ADD"]).replace("$", "").replace(",", "")
            preco = float(preco_str)
            qtd_str = str(tabela_df.loc[i, "QTD"]).replace(" UN", "").replace(",", "")
            qtd = float(qtd_str)
            stop_pct_str = str(tabela_df.loc[i, "STOP"]).replace("%", "")
            stop_pct = float(stop_pct_str)
            stop_price = preco * (1 - stop_pct / 100)
            risco = (preco - stop_price) * qtd
            total_risco_operacao += risco
        except ValueError:
            continue

faixa_total = total_risco_operacao + lucro_estimado_total
if faixa_total == 0:
    faixa_total = 1

# Calcula a posição percentual do lucro real na faixa total
progresso_pct = (lucro_real / faixa_total) * 100
posicao_pct = 50 + (lucro_real / (2 * faixa_total)) * 100
posicao_pct = max(0, min(100, posicao_pct))

# Determina cor e sinal
cor_valor = "#28a745" if lucro_real >= 0 else "#dc3545"
sinal = "+" if lucro_real >= 0 else "-"

# Mostra barra com valor atual e posição visual
st.markdown("---")
st.markdown(f"""
    <div font-size: 17px;'>
        <strong>⚖️ Balança das posições em aberto (R/R {rr_ratio:.2f}) <br>
        <br>
    </div>
    """, unsafe_allow_html=True)

st.markdown(f"""
<div style='position: relative; width: 100%; height: 30px; background: linear-gradient(to right, #dc3545, #6c757d, #28a745); 
            border-radius: 10px; margin-bottom: 5px;'>
    <div style='position: absolute; left: {posicao_pct}%;bottom: -30px; transform: translateX(-50%); font-weight: bold; font-size: 14px; color:{cor_valor};'>
    {sinal}${abs(lucro_real):,.2f}</div>
        <div style='position: absolute; left: {posicao_pct}%; top: -30px; transform: translateX(-50%); font-weight: bold; font-size: 14px; color:{cor_valor};'>{progresso_pct:.1f}%</div>
<div style='position: absolute; left: {posicao_pct}%; top: 0; bottom: 0; width: 3px; background-color: #ffffff77;'></div>
</div>
<div style='position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background-color: #ffffff77;'></div>
</div>
<div style='display: flex; justify-content: space-between; font-size: 14px;'>
    <span style='color: #dc3545;'>📉 -${total_risco_compras_reais:,.0f}</span>
    <span style='color: #28a745;'>+${lucro_estimado_total:,.0f} 💰</span>
</div>
""", unsafe_allow_html=True)











# Cálculo das posições percentuais e cores
pl_executado = total_pct_pl_executado
pl_planejado = total_pct_pl_planejado
barra_max = max(pl_planejado, pl_executado, 100, 150)

executado_pct = (pl_executado / barra_max) * 100
planejado_pct = (pl_planejado / barra_max) * 100
ideal_pct = (100 / barra_max) * 100

cor_barra = "#28a745" if pl_planejado <= 100 else "#ffc107" if pl_planejado <= 120 else "#dc3545"
cor_exec = "#006400"
cor_plan = "#ff8c00"




# Cabeçalho
st.markdown("---")
st.markdown(f"""
    <div font-size: 17px;'>
        <strong> 🧮 Comprometimento do PL Projetado (Qnt Atual: {qtd_simulacoes} ativos)<br>
        <br>
    </div>
    """, unsafe_allow_html=True)
# Renderiza barra com legenda
st.markdown(f"""
<!-- Legenda acima -->
<div style='position: relative; width: 100%; height: 25px; font-weight: bold; margin-bottom: 4px; font-size: 14px;'>
  <div style='position: absolute; left: {executado_pct:.2f}%; transform: translateX(-50%); color: {cor_exec};'>📍 Atual</div>
  <div style='position: absolute; left: {planejado_pct:.2f}%; transform: translateX(-50%); color: {cor_plan};'>🔮 Após Compras</div>
</div>

<!-- Barra visual -->
<div style='position: relative; width: 100%; height: 30px; 
             background: linear-gradient(to right, #e2f7d5, #fff3cd, #f8d7da); 
             border-radius: 10px; margin-bottom: 30px;'>

  <!-- Executado -->
  <div style='position: absolute; left: {executado_pct:.2f}%; bottom: -26px; 
              transform: translateX(-50%); font-size: 14px; color: {cor_exec};'>
      {pl_executado:.1f}%
  </div>
  <div style='position: absolute; left: {executado_pct:.2f}%; top: 0; bottom: 0; 
              width: 2px; background-color: {cor_exec};'></div>

  <!-- Planejado -->
  <div style='position: absolute; left: {planejado_pct:.2f}%; bottom: -26px; 
              transform: translateX(-50%); font-size: 14px; color: {cor_plan};'>
      {pl_planejado:.1f}%
  </div>
  <div style='position: absolute; left: {planejado_pct:.2f}%; top: 0; bottom: 0; 
              width: 2px; background-color: {cor_plan};'></div>

  <!-- Ideal -->
  <div style='position: absolute; left: {ideal_pct:.2f}%; top: 0; bottom: 0; 
              width: 1px; background-color: #6f6f6f;'></div>
</div>

<!-- Escala com marcador alinhado à barra de 100% -->
<div style='position: relative; width: 100%; height: 20px; margin-top: -10px; font-size: 15px;'>
  <div style='position: absolute; left: 0%;'>0%</div>
  <div style='position: absolute; left: {ideal_pct:.2f}%; transform: translateX(-50%); color: #333;'>🎯 100% do PL</div>
  <div style='position: absolute; right: 0%; text-align: right;'>{barra_max:.0f}% Alavancado</div>
</div>

""", unsafe_allow_html=True)








# DASHBOARD DE RANKING (Adicione este bloco ao final do seu arquivo)
st.markdown("---")
st.subheader("🏆 Ranking de Ativos por Progresso")

ativos_progresso = []
max_progresso_abs = 0  # Encontra o maior valor absoluto para normalizar
for sim in st.session_state.simulacoes:
    nome = sim["nome"]
    preco_medio = sim.get("preco_medio", 0)
    preco_final = sim.get("preco_final", 0)
    valor_atual = get_preco_atual(nome) or sim.get("preco_medio", 0)
    progresso_ate_meta = ((valor_atual - preco_medio) / (preco_final - preco_medio)) * 100 if (preco_final - preco_medio) else 0
    if progresso_ate_meta < 0:
        progresso_ate_meta *= 2  # Multiplica por 2 se o lucro for negativo
    ativos_progresso.append({"nome": nome, "progresso": progresso_ate_meta})
    max_progresso_abs = max(max_progresso_abs, abs(progresso_ate_meta))

ativos_ordenados = sorted(ativos_progresso, key=lambda x: x["progresso"], reverse=True)

for i, ativo in enumerate(ativos_ordenados):
    nome = ativo["nome"]
    progresso = ativo["progresso"]
    progresso_normalizado = (progresso / max_progresso_abs) * 50 if max_progresso_abs else 0
    largura_barra = abs(progresso_normalizado)
    direcao = "50%" if progresso >= 0 else f'calc(50% - {largura_barra}%)'
    cor_barra = "#28a745" if progresso >= 0 else "#dc3545"

    html = f"""
    <div style='margin-bottom: 24px; padding: 10px; border-radius: 8px; background-color: #f8f9fa;'>
        <div style='font-size: 15px; margin-bottom: 6px;'><strong>{i + 1}. {nome}</strong> | Progresso: {progresso:.1f}%</div>
        <div style='position: relative; height: 16px; background-color: #e9ecef; border-radius: 8px;'>
            <div style='position: absolute; left: {direcao}; top: 0; bottom: 0; width: {largura_barra}%;
                        background-color: {cor_barra}; border-radius: 8px;'></div>
            <div style='position: absolute; left: 50%; top: -3px; bottom: -3px; width: 2px; background-color: #00000044;'></div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# 📊 Painel de Resumo das Vendas Finalizadas
st.markdown("---")
st.markdown("### 🧾 Análise Visual das Últimas 10 Vendas")

vendas = finalizadas_ref.get() or []
ultimas_vendas = vendas[-10:] if vendas else []

if ultimas_vendas:
    max_abs_lucro = max(abs(v["lucro"]) for v in ultimas_vendas) or 1

    col_esq, col_dir = st.columns(2)

    for i, venda in enumerate(reversed(ultimas_vendas)):
        nome = venda["nome"]
        data = venda["data"]
        lucro = venda["lucro"]
        cor_barra = "#28a745" if lucro > 0 else "#dc3545"
        emoji = "🟢" if lucro > 0 else "🔴"
        texto = f"${lucro:,.2f}"

        largura = abs(lucro) / max_abs_lucro * 50
        direcao = "50%" if lucro >= 0 else f"calc(50% - {largura}%)"

        html = f"""
        <div style='margin-bottom: 24px; padding: 10px; border-radius: 8px; background-color: #f8f9fa;'>
            <div style='font-size: 15px; margin-bottom: 6px;'>
                <strong>{emoji} {i+1}. {nome}</strong> | {data} | Lucro: {texto}
            </div>
            <div style='position: relative; height: 16px; background-color: #e9ecef; border-radius: 8px;'>
                <div style='position: absolute; left: {direcao}; top: 0; bottom: 0; width: {largura}%;
                            background-color: {cor_barra}; border-radius: 8px;'></div>
                <div style='position: absolute; left: 50%; top: -3px; bottom: -3px; width: 2px;
                            background-color: #00000044;'></div>
            </div>
        </div>
        """

        if i < 5:
            col_esq.markdown(html, unsafe_allow_html=True)
        else:
            col_dir.markdown(html, unsafe_allow_html=True)

else:
    st.info("Ainda não há vendas registradas para exibir.")




    # 🔍 RESUMO FINAL DAS 10 VENDAS
lucros_positivos = [v for v in ultimas_vendas if v["lucro"] > 0]
lucros_negativos = [v for v in ultimas_vendas if v["lucro"] < 0]

qtd_lucros = len(lucros_positivos)
qtd_prejuizos = len(lucros_negativos)
soma_lucros = sum(v["lucro"] for v in lucros_positivos)
soma_prejuizos = sum(v["lucro"] for v in lucros_negativos)
lucro_liquido = soma_lucros + soma_prejuizos

cor_liquido = "#28a745" if lucro_liquido >= 0 else "#dc3545"
sinal_liquido = "🟢" if lucro_liquido >= 0 else "🔴"

st.markdown(f"""
<div style='background-color:#f8f9fa; padding: 15px; border-radius: 8px; font-size: 16px;'>
<ul>
    <li>🟢 <strong>{qtd_lucros} com lucro</strong> • Total: <span style="color:#28a745;">${soma_lucros:,.2f}</span></li>
    <li>🔴 <strong>{qtd_prejuizos} com prejuízo</strong> • Total: <span style="color:#dc3545;">${abs(soma_prejuizos):,.2f}</span></li>
    <li><strong>{sinal_liquido} Lucro líquido das 10 vendas:</strong> <span style="color:{cor_liquido};">${lucro_liquido:,.2f}</span></li>
</ul>
</div>
""", unsafe_allow_html=True)



import io
import base64

st.markdown("---")
st.markdown("### 🧾 Operações Finalizadas (Tabela Compacta)")

vendas = finalizadas_ref.get() or []

if vendas:
    total_pos = sum(1 for v in vendas if v.get("lucro", 0) > 0)
    total_neg = sum(1 for v in vendas if v.get("lucro", 0) < 0)
    total = len(vendas)
    pct_pos = (total_pos / total) * 100 if total else 0
    pct_neg = (total_neg / total) * 100 if total else 0

    st.markdown(f"""
    <div style='background-color:#f0f0f0; padding: 15px; border-radius: 10px; font-size: 16px;'>
    <ul>
        <li>✅ <strong>Total de Vendas com Lucro:</strong> {total_pos} ({pct_pos:.1f}%)</li>
        <li>❌ <strong>Total com Prejuízo:</strong> {total_neg} ({pct_neg:.1f}%)</li>
        <li>📦 <strong>Total de Vendas Registradas:</strong> {total}</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    # Pega as simulações completas salvas no Firebase (ativas ou não)
    sim_ativas = ref.get() or []
    sim_por_nome = {sim["nome"]: sim for sim in sim_ativas}

    dados_tabela = []
    for venda in reversed(vendas):  # Mais recentes primeiro
        nome = venda["nome"]
        sim = sim_por_nome.get(nome)

        # Tenta extrair a compra inicial
        data_compra = "—"
        preco_compra = None

        if sim and "compras_reais" in sim:
            compras = sim["compras_reais"]
            if len(compras) > 0:
                primeira = compras[0]
                data_compra = primeira.get("data", "—")
                preco_compra = primeira.get("preco")

        dados_tabela.append({
            "Ativo": nome,
            "Data Venda": venda["data"],
            "Preço Venda": f"${venda['preco_venda']:.2f}",
            "Qtd": venda["quantidade"],
            "Lucro ($)": f"${venda['lucro']:.2f}",
            "Lucro (%)": f"{venda['lucro_pct']:.1f}%",
            "Tipo": venda["tipo"],
            "Data Compra": data_compra,
            "Preço Compra": f"${preco_compra:.2f}" if preco_compra else "—",
        })

    df = pd.DataFrame(dados_tabela)

    st.dataframe(df, use_container_width=True, hide_index=True)

    # Botão de download CSV
    csv = df.to_csv(index=False).encode('utf-8')
    b64 = base64.b64encode(csv).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="vendas_finalizadas.csv">📥 Baixar CSV</a>'
    st.markdown(href, unsafe_allow_html=True)
    # 🔻 Excluir múltiplas vendas
   # 🔻 Excluir múltiplas vendas
    st.markdown("#### 🗑 Excluir vendas selecionadas")

    # Cria lista de exibição com índice reverso para manter ordem (mais recente primeiro)
    opcoes_exclusao = [
        f"{v['data']} | {v['nome']} | {v['quantidade']} ações a ${v['preco_venda']:.2f}"
        for v in reversed(vendas)
    ]
    selecionadas = st.multiselect("Selecione uma ou mais vendas para excluir:", opcoes_exclusao)

    botao_excluir = st.button("🗑 Excluir selecionadas")

    if botao_excluir:
        if not st.session_state.selecionadas_exclusao:
            st.warning("⚠️ Selecione ao menos uma venda para excluir.")
        else:
            vendas_restantes = vendas.copy()

            indices_para_remover = [
                len(vendas) - 1 - st.session_state.selecionadas_exclusao.index(s)
                for s in st.session_state.selecionadas_exclusao
            ]
            indices_para_remover.sort(reverse=True)

            for idx in indices_para_remover:
                if 0 <= idx < len(vendas_restantes):
                    vendas_restantes.pop(idx)

            finalizadas_ref.set(limpar_chaves_invalidas(vendas_restantes))
            st.success(f"✅ {len(st.session_state.selecionadas_exclusao)} venda(s) excluída(s) com sucesso.")
            st.session_state.selecionadas_exclusao = []  # limpa após exclusão
            st.rerun()





else:
    st.info("Nenhuma venda registrada ainda para análise.")
