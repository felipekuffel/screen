# screener/layout.py

import streamlit as st

def aplicar_zoom(percentual=70):
    escala = percentual / 100
    proporcao = 100 / escala  # ex: 100 / 0.7 = 143%

    st.markdown(f"""
        <style>
        html, body {{
            overflow: hidden;
        }}
        [data-testid="stApp"] {{
            transform: scale({escala});
            transform-origin: top left;
            position: fixed;
            top: 0;
            left: 0;
            width: {proporcao:.0f}%;
            height: {proporcao:.0f}%;
            overflow: scroll;
        }}
        </style>
    """, unsafe_allow_html=True)
