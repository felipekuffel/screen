import streamlit as st
import pandas as pd
import numpy as np
from cryptography.hazmat.primitives import serialization
import re
import datetime
from firebase_admin import credentials, auth as admin_auth, db
import firebase_admin


# Verifica se o usuário está autenticado
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Você precisa estar logado para acessar esta página.")
    st.link_button("🔐 Ir para Login", "/")
    st.stop()
    
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
    <div style="text-align: right; margin-top: -20px; margin-bottom: 20px;">
        <img src="https://i.ibb.co/1tCRXfWv/404aabba-df44-4fc5-9c02-04d5b56108b9.png" width="120">
        <h5 style="margin-top: 8px;">Salve seus registros de compras</h5>
    </div>
""", unsafe_allow_html=True)


st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

try:
    key = st.secrets["firebase_admin"]["private_key"]
    serialization.load_pem_private_key(key.encode(), password=None)
except Exception as e:
    st.error(f"❌ Erro na chave privada: {e}")
    st.stop()

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase_admin"]))
        firebase_admin.initialize_app(cred, {
            "databaseURL": st.secrets["databaseURL"]
        })
    except Exception as e:
        st.error(f"Erro ao inicializar Firebase: {e}")
        st.stop()

if "user" not in st.session_state or "localId" not in st.session_state.user:
    st.error("Usuário não autenticado corretamente.")
    st.stop()

user_id = st.session_state.user["localId"]
ref = db.reference(f"carteiras/{user_id}/simulacoes")
finalizadas_ref = db.reference(f"carteiras/{user_id}/simulacoes_finalizadas")
simulacoes_salvas = ref.get()

if "simulacoes" not in st.session_state:
    st.session_state.simulacoes = simulacoes_salvas if simulacoes_salvas else []

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
        "data": data_venda,
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
else:
    nome_default = "ACMR"
    cotacao_default = 28.87
    venda_pct_default = 17.0
    pl_total_default = 10000.0





with st.expander("📝 Nova Simulação de Compra", expanded=False):

    st.subheader("📌 Configuração das Compras")
    # Entradas dinâmicas com atualização imediata
    col1, col2, col3, col4, col5= st.columns(5)
    with col1:
        nome_acao = st.text_input("🔹 Nome da Ação", nome_default, key="nome_acao_live")
    with col2:
        cotacao = st.number_input("💲 Cotação Inicial de Compra", value=cotacao_default, step=0.01, format="%.2f", key="cotacao_live")
    with col3:
        venda_pct = st.number_input("🎯 % de Ganho para Venda", value=venda_pct_default, step=0.1, format="%.2f", key="venda_pct_live")
    with col4:
        pl_total = st.number_input("💼 Capital Total (PL)", value=pl_total_default, step=100.0, key="pl_total_live")
    with col5:
        data_simulacao = st.date_input("📅 Data da Simulação", value=datetime.date.today(), key="data_simulacao_live")

    st.markdown("---")

    # Risco máximo configurável pelo usuário
    risco_maximo_pct = st.number_input("🔻 Risco máximo da operação total em relação ao PL (%)", value=1.0, step=0.1, key="risco_maximo_pct")

    st.markdown("---")
    st.subheader("📌 Configuração das Compras")

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
                    label_subida = f"🔼 % de Subida → ${preco_entrada:.2f}"
                    subida = st.number_input(label_subida, key=f"subida{i}", value=subida_temp, step=0.1)

            with col2:
                pct_pl_padrao = [8.0, 6.0, 6.0][i]
                pct_pl_temp = st.session_state.get(f"pct_pl{i}", pct_pl_padrao)
                valor_investido = st.session_state.pl_total_live * (pct_pl_temp / 100)
                qtd_calculada = valor_investido / preco_entrada if preco_entrada else 0
                label_pl = f"📊 % do PL (Qtd: {int(qtd_calculada)} UN)"
                pct_pl = st.number_input(label_pl, key=f"pct_pl{i}", value=pct_pl_temp, step=0.1)

            with col3:
                stop_padrao = [8.0, 8.0, 10.0][i]
                stop_pct = st.session_state.get(f"stop{i}", stop_padrao)
                stop_price = preco_entrada * (1 - stop_pct / 100) if preco_entrada else 0
                label_stop = f"🛑 Stop (%) → ${stop_price:.2f}"
                stop = st.number_input(label_stop, key=f"stop{i}", value=stop_pct, step=0.1)

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


    

    # ✅ Apenas o botão fica dentro do form
    with st.form("form_compras_final"):
        enviado = st.form_submit_button("📥 Confirmar Planejamento de Compras")

    # Processamento
    if enviado:
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

        nova_simulacao = {
            "nome": st.session_state.nome_acao_live,
            "cotacao": st.session_state.cotacao_live,
            "venda_pct": st.session_state.venda_pct_live,
            "pl_total": st.session_state.pl_total_live,
            "data_simulacao": str(st.session_state.data_simulacao_live),
            "preco_final": preco_final,
            "lucro": lucro,
            "lucro_pct": lucro_pct,
            "lpl_pct": lpl_pct,
            "total_valor": total_valor,
            "total_unidades": total_unidades,
            "tabela": df_tabela.to_dict(),
            "quantidade_restante": int(total_unidades),
            "risco_maximo_pct": st.session_state.get("risco_maximo_pct", 1.0),
            "compras_reais": [
                {
                    "etapa": "Inicial",
                    "preco": st.session_state.cotacao_live,
                    "qtd": int(st.session_state.pl_total_live * (compra_data[0]["pct_pl"] / 100) / st.session_state.cotacao_live),
                    "data": str(st.session_state.data_simulacao_live)
                }
            ],
            "quantidade_real": int(st.session_state.pl_total_live * (compra_data[0]["pct_pl"] / 100) / st.session_state.cotacao_live),
            "preco_medio": st.session_state.cotacao_live
        }

        st.session_state.simulacoes.append(nova_simulacao)
        ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
        st.success("✅ Simulação salva com sucesso!")
        st.rerun()


        enviado = st.form_submit_button("📥 Simular Compras")



if enviado:
    if 'edit_index' in st.session_state:
        del st.session_state.simulacoes[st.session_state.edit_index]
        del st.session_state.edit_index

    total_valor = 0
    total_unidades = 0
    linhas = []

    for i, compra in enumerate(compra_data):
        preco = cotacao * (1 + compra["subida_pct"] / 100)
        valor = pl_total * (compra["pct_pl"] / 100)
        unidades = valor / preco
        stop_preco = preco * (1 - compra["stop_pct"] / 100)
        risco_valor = (preco - stop_preco) * unidades
        risco_pct_pl = -risco_valor / pl_total * 100

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

    preco_final = cotacao * (1 + venda_pct / 100)
    lucro = preco_final * total_unidades - total_valor
    lucro_pct = lucro / total_valor * 100
    lpl_pct = lucro / pl_total * 100

    df_tabela = pd.DataFrame(linhas, columns=[
        "Etapa", "ADD", "% PARA COMPRA", "COMPRA PL", "% PL COMPRA",
        "QTD", "STOP", "$ STOP", "RISCO", "$ RISCO"
    ])

    nova_simulacao = {
        "nome": nome_acao,
        "cotacao": cotacao,
        "venda_pct": venda_pct,
        "pl_total": pl_total,
        "data_simulacao": str(data_simulacao),  # <- campo novo
        "preco_final": preco_final,
        "lucro": lucro,
        "lucro_pct": lucro_pct,
        "lpl_pct": lpl_pct,
        "total_valor": total_valor,
        "total_unidades": total_unidades,
        "tabela": df_tabela.to_dict(),
        "quantidade_restante": int(total_unidades),
        "compras_reais": [
            {
                "etapa": "Inicial",
                "preco": cotacao,
                "qtd": int(pl_total * (compra_data[0]["pct_pl"] / 100) / cotacao),
                "data": str(data_simulacao)
            }
        ],
        "quantidade_real": int(pl_total * (compra_data[0]["pct_pl"] / 100) / cotacao),
        "preco_medio": cotacao
    }

    st.session_state.simulacoes.append(nova_simulacao)
    ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
    st.success("✅ Simulação salva com sucesso!")
    st.rerun()

st.markdown("---")
st.subheader("📈 Simulações em Aberto")

for idx, sim in enumerate(st.session_state.simulacoes):
    preco_medio = sim.get("preco_medio", 0)
    preco_final = sim.get("preco_final", 0)

    try:
        import yfinance as yf
        ticker = yf.Ticker(sim["nome"])
        valor_atual = ticker.history(period="1d")["Close"].iloc[-1]
    except Exception:
        valor_atual = preco_medio

    progresso_pct = (valor_atual / preco_medio - 1) * 100 if preco_medio else 0
    progresso_ate_meta = ((valor_atual - preco_medio) / (preco_final - preco_medio)) * 100 if (preco_final - preco_medio) else 0
    restante_para_meta = ((preco_final - valor_atual) / valor_atual) * 100 if valor_atual else 0

    cor_progresso = "#28a745" if progresso_pct >= 0 else "#dc3545"
    icone_progresso = "🔼" if progresso_pct >= 0 else "🔽"

    alerta = ""
    try:
        compra_2_pct = float(sim["tabela"]["% PARA COMPRA"][1].replace('%', ''))
        compra_3_pct = float(sim["tabela"]["% PARA COMPRA"][2].replace('%', ''))
        preco_2 = sim["cotacao"] * (1 + compra_2_pct / 100)
        preco_3 = sim["cotacao"] * (1 + compra_3_pct / 100)

        if valor_atual < preco_2:
            alerta = "🟢 Em faixa da COMPRA INICIAL"
        elif valor_atual < preco_3:
            alerta = "🟡 Em faixa da COMPRA 2"
        else:
            alerta = "🟠 Em faixa da COMPRA 3 ou acima"
    except:
        pass

    destaque_cor = "#e6fff2"
    if valor_atual >= preco_final:
        alerta = "🎉 Preço atual ultrapassou o alvo!"
        destaque_cor = "#fff3cd"

    
        # 🔍 Etapa atual (para inline)
    etapas_executadas = [c["etapa"] for c in sim.get("compras_reais", [])]
    if "3" in etapas_executadas:
        aviso_etapa_inline = "🟠 Compra atual: COMPRA 3"
    elif "2" in etapas_executadas:
        aviso_etapa_inline = "🟡 Compra atual: COMPRA 2"
    elif "Inicial" in etapas_executadas:
        aviso_etapa_inline = "🟢 Compra atual: COMPRA INICIAL"
    else:
        aviso_etapa_inline = "⚠️ Nenhuma compra real"

    expander_aberto = st.session_state.get("keep_open_idx") == idx
    with st.expander(
        f"📈 {sim['nome']}  •  Alvo:  {preco_final:.2f} (+{sim['venda_pct']:.1f}% ) •  Lucro: ${sim['lucro']:.2f}  •  Progresso: {progresso_ate_meta:.1f}%  •  Falta subir: {restante_para_meta:.1f}%  •  {alerta} • {aviso_etapa_inline}",
        expanded=expander_aberto,
    ):
        st.markdown(f"""
        <div style='padding: 1rem; background-color: {destaque_cor}; border-radius: 10px; font-size: 16px;'>
            <p><strong>💰 Preço Médio:</strong> $ {preco_medio:.2f} &nbsp;&nbsp;|&nbsp;&nbsp; 
            <strong>💵 Preço Atual:</strong> $ {valor_atual:.2f} &nbsp;&nbsp;|&nbsp;&nbsp; 
            <strong>🎯 Meta de Venda:</strong> $ {preco_final:.2f} &nbsp;&nbsp;|&nbsp;&nbsp; 
            <strong>📊 Variação Atual:</strong> {progresso_pct:.2f}%<>
            <strong>📈 Progresso até a Meta:</strong> <span style='color: {cor_progresso};'>{icone_progresso} {progresso_ate_meta:.2f}%</span> &nbsp;&nbsp;•&nbsp;&nbsp; <strong>🔺 Falta subir:</strong> {restante_para_meta:.2f}% &nbsp;&nbsp; {alerta}</p>
        </div>
        """, unsafe_allow_html=True)

        st.progress(max(0.0, min(progresso_ate_meta / 100, 1.0)))

       

        

        st.dataframe(pd.DataFrame(sim["tabela"], columns=sim["tabela"].keys()), use_container_width=True, hide_index=True)

        st.markdown(f"""
        <div style='padding: 1rem; background-color: #f0f2f6; border-radius: 10px; font-size: 16px;'>
        <p><strong>Objetivos da Operação:</strong>&nbsp;&nbsp;
        <strong>📦 Qtd total:</strong> {int(sim['total_unidades'])} ações &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>💼 Total investido:</strong> $ {sim['total_valor']:.2f} &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>📊 Lucro estimado:</strong> $ {sim['lucro']:.2f} ({sim['lucro_pct']:.2f}%) &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>L/PL:</strong> {sim['lpl_pct']:.2f}%</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"")
        col_hist, col_botoes = st.columns([2, 3])

        with col_hist:
            if "compras_reais" in sim and sim["compras_reais"]:
                total_disponivel = sim.get("quantidade_real", 0)
                preco_medio = sim.get("preco_medio", 0)
                total_investido = sum([c["preco"] * c["qtd"] for c in sim["compras_reais"]])

                st.markdown("""
                <div style='padding: 1rem; background-color: #f8f9fa; border-radius: 10px; font-size: 16px;'>
                    <p><strong>📦 Ações disponíveis para venda:</strong> {disponivel} ações</p>
                    <p><strong>💰 Preço médio acumulado:</strong> $ {preco:.2f}</p>
                    <p><strong>💸 Total investido nas compras reais:</strong> $ {investido:.2f}</p>
                </div>
                """.format(disponivel=total_disponivel, preco=preco_medio, investido=total_investido), unsafe_allow_html=True)

                st.markdown("#### 📜 Histórico de Compras Reais")
                for i, c in enumerate(sim["compras_reais"]):
                    with st.container():
                        col1, col2 = st.columns([5, 1])
                        with col1:
                            st.markdown(
                                f"🛒 **Compra {i+1} ({c.get('etapa', '?')})** | "
                                f"📅 {c.get('data', '—')} • "
                                f"🔢 {c['qtd']} ações • "
                                f"💵 $ {c['preco']:.2f}"
                            )
                        with col2:
                            if st.button("🗑", key=f"excluir_compra_{sim['nome']}_{idx}_{i}"):
                                compra_removida = sim["compras_reais"].pop(i)

                                # Se ficou vazio, garantir que a chave ainda exista
                                if not sim["compras_reais"]:
                                    sim["compras_reais"] = []

                                # Restaurar nome e dados da etapa na tabela, se for COMPRA 2 ou 3
                                if compra_removida["etapa"] in ["2", "3"]:
                                    etapa = compra_removida["etapa"]
                                    etapa_nome_real = f"COMPRA {etapa} - Real"
                                    etapa_nome_original = f"COMPRA {etapa}"
                                    tabela_df = pd.DataFrame(sim["tabela"])
                                    idx_linha = tabela_df[tabela_df["Etapa"] == etapa_nome_real].index

                                    if not idx_linha.empty:
                                        i = idx_linha[0]
                                        pl_total = sim["pl_total"]
                                        cotacao_inicial = sim["cotacao"]

                                        # Restaurar % PL COMPRA original
                                        try:
                                            pct_pl_original = float(str(tabela_df.at[i, "% PL COMPRA"]).replace("%", ""))
                                        except:
                                            pct_pl_original = 6.0 if etapa == "2" else 6.0

                                        # Subida padrão da etapa
                                        subida_padrao = 4.0 if etapa == "2" else 10.0
                                        preco_simulado = cotacao_inicial * (1 + subida_padrao / 100)
                                        valor = pl_total * (pct_pl_original / 100)
                                        qtd = valor / preco_simulado

                                        try:
                                            stop_pct = float(str(tabela_df.at[i, "STOP"]).replace("%", ""))
                                        except:
                                            stop_pct = 8.0

                                        stop_price = preco_simulado * (1 - stop_pct / 100)

                                        # Restaurar linha da tabela com os dados originais
                                        tabela_df.at[i, "Etapa"] = etapa_nome_original
                                        tabela_df.at[i, "ADD"] = f"${preco_simulado:.2f}"
                                        tabela_df.at[i, "QTD"] = f"{int(qtd)} UN"
                                        tabela_df.at[i, "COMPRA PL"] = f"${valor:,.2f}"
                                        tabela_df.at[i, "% PL COMPRA"] = f"{pct_pl_original:.2f}%"
                                        tabela_df.at[i, "% PARA COMPRA"] = f"{subida_padrao:.2f}%"
                                        tabela_df.at[i, "$ STOP"] = f"$ {stop_price:.2f}"
                                        tabela_df.at[i, "STOP"] = f"{stop_pct:.2f}%"

                                        sim["tabela"] = tabela_df.to_dict(orient="list")

                                # Atualiza valores acumulados
                                total_qtd = sum([c["qtd"] for c in sim["compras_reais"]])
                                total_valor = sum([c["preco"] * c["qtd"] for c in sim["compras_reais"]]) if sim["compras_reais"] else 0
                                sim["quantidade_real"] = total_qtd
                                sim["preco_medio"] = total_valor / total_qtd if total_qtd else 0

                                # Recalcula riscos e atualiza
                                sim = recalcular_riscos(sim)
                                st.session_state.simulacoes[idx] = sim
                                ref.set(limpar_chaves_invalidas(st.session_state.simulacoes))
                                st.session_state["keep_open_idx"] = idx
                                st.success("🗑 Compra excluída com sucesso!")
                                st.rerun()



        with col_botoes:
            col_ed, col_del = st.columns([1, 1])
            with col_ed:
                if st.button(f"✏️ Editar {sim['nome']}", key=f"edit_{idx}"):
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

                    data_venda = st.date_input("📅 Data da venda", value=datetime.date.today(), key=f"data_venda_{idx}")
                    preco_venda = st.number_input("💲 Preço de venda", step=0.01, format="%.2f", key=f"preco_venda_{idx}")
                    
                    if disponivel > 0:
                        qtd_vendida = st.number_input("🔢 Quantidade vendida", step=1, format="%d", key=f"qtd_vendida_{idx}", min_value=1, max_value=disponivel)
                        if st.form_submit_button("Confirmar Venda"):
                            registrar_venda(sim, preco_venda, qtd_vendida, str(data_venda))
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
                                stop_pct = float(str(row["STOP"]).replace("%", ""))
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
                        data_compra = st.date_input("📅 Data da compra", value=datetime.date.today(), key=f"data_compra_{idx}")

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

                            compra_inicial = next((c for c in sim["compras_reais"] if c["etapa"] == "Inicial"), None)
                            if compra_inicial:
                                preco1 = compra_inicial["preco"]
                                qtd1 = compra_inicial["qtd"]
                                if risco_max_inicial > 0:
                                    novo_stop1 = preco1 - (risco_max_inicial / qtd1)
                                    novo_stop1_pct = (preco1 - novo_stop1) / preco1 * 100
                                    tabela_df.loc[tabela_df["Etapa"] == "COMPRA INICIAL", "STOP"] = f"{novo_stop1_pct:.2f}%"
                                    sim["tabela"] = tabela_df.to_dict(orient="list")
                                    st.success(f"📉 Stop da COMPRA INICIAL pode ser {novo_stop1_pct:.2f}% para manter risco ≤ 1% do PL")

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
                                "data": str(data_compra)
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

# Apresentação em 2 colunas estilizadas
col1, col2 = st.columns(2)

with col1:
    st.markdown(f"""
    <div style='padding: 1rem; background-color: #eef5f9; border-radius: 10px; font-size: 17px;'>
        <strong>💰 Lucro estimado total:</strong> $ {lucro_estimado_total:,.2f}<br>
        <strong>📉 Risco total real:</strong> $ {total_risco_compras_reais:,.2f}<br>
        <strong>📈 R/R médio esperado:</strong> {rr_ratio:.2f}

    </div>
    """, unsafe_allow_html=True)


with col2:
    st.markdown(f"""
    <div style='padding: 1rem; background-color: #eef9f1; border-radius: 10px; font-size: 17px;'>
        <strong>📁 Simulações em aberto:</strong> {qtd_simulacoes}<br>
        <strong>📊 PL comprometido nas compras:</strong> {total_pct_pl_executado:.2f}%<br>
        <strong>💼 PL necessário após todas as compras:</strong> {total_pct_pl_planejado:.2f}%

    </div>
    """, unsafe_allow_html=True)






st.markdown("---")
st.subheader("📁 Simulações Finalizadas")
vendas_registradas = finalizadas_ref.get()
if vendas_registradas:
    for i, venda in enumerate(vendas_registradas[::-1]):
        with st.expander(f"{venda['tipo']} {venda['nome']} • {venda['data']} • {venda['quantidade']} ações vendidas a $ {venda['preco_venda']:.2f}"):
            st.markdown(f"""
            - 💰 **Lucro:** $ {venda['lucro']:.2f} ({venda['lucro_pct']:.2f}%)
            - 📆 **Data:** {venda['data']}
            - 📉 **Preço de venda:** $ {venda['preco_venda']:.2f}
            - 🔢 **Quantidade vendida:** {venda['quantidade']} ações
            """)
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button(f"✏️ Editar venda", key=f"editar_venda_{i}"):
                    with st.form(f"editar_venda_form_{i}"):
                        nova_data = st.date_input("📅 Nova data da venda", value=datetime.date.fromisoformat(venda["data"]), key=f"data_edit_{i}")
                        novo_preco = st.number_input("💲 Novo preço de venda", value=venda["preco_venda"], step=0.01, format="%.2f", key=f"preco_edit_{i}")
                        nova_qtd = st.number_input("🔢 Nova quantidade vendida", value=int(venda["quantidade"]), step=1, key=f"qtd_edit_{i}")
                        if st.form_submit_button("Salvar alterações"):
                            valor_total_venda = novo_preco * nova_qtd
                            valor_total_custo = (venda["lucro"] + venda["preco_venda"] * venda["quantidade"] - valor_total_venda)
                            lucro = valor_total_venda - valor_total_custo
                            lucro_pct = lucro / valor_total_custo * 100 if valor_total_custo != 0 else 0
                            venda_editada = {
                                **venda,
                                "data": str(nova_data),
                                "preco_venda": novo_preco,
                                "quantidade": nova_qtd,
                                "lucro": lucro,
                                "lucro_pct": lucro_pct
                            }
                            vendas_registradas[i] = venda_editada
                            finalizadas_ref.set(limpar_chaves_invalidas(vendas_registradas))
                            st.success("Venda editada com sucesso!")
                            st.rerun()
            with col2:
                if st.button(f"🗑 Excluir venda", key=f"excluir_venda_{i}"):
                    vendas_restantes = vendas_registradas.copy()
                    vendas_restantes.pop(len(vendas_registradas) - 1 - i)
                    finalizadas_ref.set(limpar_chaves_invalidas(vendas_restantes))
                    st.success("Venda removida com sucesso!")
                    st.rerun()
else:
    st.info("Nenhuma venda registrada ainda.")
