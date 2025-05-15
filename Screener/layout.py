# screener/layout.py

import streamlit as st

# Verifica se o usuário está autenticado
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Você precisa estar logado para acessar esta página.")
    st.link_button("🔐 Ir para Login", "/")
    st.stop()


def aplicar_zoom(percentual=70):
    escala = percentual / 100
    proporcao = 100 / escala  # Ex: 1/0.7 = 143%

    st.markdown(f"""
        <style>
        [data-testid="stApp"] {{
            transform: scale({escala});
            transform-origin: top left;
            width: {proporcao:.0f}%;
        }}
        html, body {{
            overflow-x: hidden;
        }}
        </style>
    """, unsafe_allow_html=True)
