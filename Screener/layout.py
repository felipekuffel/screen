# screener/layout.py

import streamlit as st

# Verifica se o usuário está autenticado
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Você precisa estar logado para acessar esta página.")
    st.link_button("🔐 Ir para Login", "/")
    st.stop()


def aplicar_zoom(percentual=70):
    escala = percentual / 100

    st.markdown(f"""
        <style>
        [data-testid="stApp"] {{
            zoom: {percentual}%;
            -moz-transform: scale({escala});
            -moz-transform-origin: top left;
            -webkit-transform: scale({escala});
            -webkit-transform-origin: top left;
            transform: scale({escala});
            transform-origin: top left;
        }}
        </style>
    """, unsafe_allow_html=True)
