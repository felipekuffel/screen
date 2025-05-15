# screener/layout.py

import streamlit as st

# Verifica se o usuário está autenticado
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Você precisa estar logado para acessar esta página.")
    st.link_button("🔐 Ir para Login", "/")
    st.stop()



def aplicar_zoom(percentual=80):
    escala = percentual / 100
    proporcao = 100 / escala

    st.markdown(f"""
        <style>
        /* Zoom padrão */
        html {{
            zoom: {percentual}%;
        }}

        /* Fallback para navegadores que ignoram zoom */
        body > div:first-child {{
            transform: scale({escala});
            transform-origin: top left;
            width: {proporcao:.0f}%;
            height: {proporcao:.0f}%;
            overflow: auto;
        }}

        /* Ajuste visual para dropdowns renderizados fora do escopo */
        [data-baseweb="popover"], [role="listbox"], [data-testid="stSelectbox"] {{
            zoom: {percentual}%;
        }}
        </style>
    """, unsafe_allow_html=True)
