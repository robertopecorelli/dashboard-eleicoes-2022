"""
Dashboard Eleições 2022 — Deputados Federais Eleitos
Cruzamento: Despesas de Campanha (TSE) x Votação (TSE) x População (IBGE)
"""

import os
import pandas as pd
import plotly.express as px
import streamlit as st
import json
import urllib.request

# ----------------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------------
CARGO_FILTRO = "DEPUTADO FEDERAL"
CAMINHO_DADOS_LIMPOS = "dados_limpos.csv"

# Configuração padrão para bloquear o zoom e os botões em todos os gráficos
CONFIG_GRAFICOS = {'displayModeBar': False, 'scrollZoom': False}

st.set_page_config(
    page_title="Dashboard Eleições 2022 - Custo por Voto",
    layout="wide",
)

# ----------------------------------------------------------------------------
# Carga de dados (CSV e Mapa GeoJSON)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="Carregando dados...")
def carregar_dados() -> pd.DataFrame:
    if os.path.exists(CAMINHO_DADOS_LIMPOS):
        return pd.read_csv(CAMINHO_DADOS_LIMPOS, sep=";", encoding="latin1")
    else:
        raise FileNotFoundError("Arquivo dados_limpos.csv não encontrado no repositório.")

@st.cache_data(show_spinner="Carregando mapa do Brasil...")
def carregar_geojson():
    # Puxa as fronteiras dos estados brasileiros de um repositório público confiável
    url = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode())

# ----------------------------------------------------------------------------
# App principal
# ----------------------------------------------------------------------------
st.title("Dashboard Eleições 2022 - Deputados Federais Eleitos")
st.caption("Cruzamento de Despesas de Campanha (TSE), Votação (TSE) e População (IBGE)")

try:
    dados = carregar_dados()
    geojson_brasil = carregar_geojson()
    
    # --- EXPULSA OS "NÃO ELEITOS" DO ARQUIVO ---
    if "DS_SIT_TOT_TURNO" in dados.columns:
        dados = dados[~dados["DS_SIT_TOT_TURNO"].str.upper().str.contains("NÃO ELEITO", na=False)]
        
except FileNotFoundError as e:
    st.error(f"Erro de arquivo: {e}")
    st.stop()

if dados.empty:
    st.warning("Nenhum registro encontrado para o cargo/situação filtrados.")
    st.stop()

# ---- Sidebar: filtros ----
st.sidebar.header("Filtros")

ufs_disponiveis = sorted(dados["SG_UF"].dropna().unique())
uf_selecionadas = st.sidebar.multiselect("Estado (UF)", ufs_disponiveis, default=ufs_disponiveis)

partidos_disponiveis = sorted(dados["SG_PARTIDO"].dropna().unique())
partidos_selecionados = st.sidebar.multiselect(
    "Partido", partidos_disponiveis, default=partidos_disponiveis
)

dados_filtrados = dados[
    dados["SG_UF"].isin(uf_selecionadas) & dados["SG_PARTIDO"].isin(partidos_selecionados)
]

# ---- KPIs rápidos ----
col1, col2, col3, col4 = st.columns(4)

# Ajuste da métrica para mostrar em relação ao limite real da câmara (513)
total_eleitos = dados_filtrados['SQ_CANDIDATO'].nunique()
col1.metric("Candidatos eleitos", f"{total_eleitos} de 513")

col2.metric("Despesa total", f"R$ {dados_filtrados['VR_DESPESA_TOTAL'].sum():,.2f}")
col3.metric("Votos totais", f"{dados_filtrados['QT_VOTOS_TOTAL'].sum():,.0f}".replace(",", "."))
custo_medio = dados_filtrados["CUSTO_POR_VOTO"].mean()
col4.metric("Custo médio/voto", f"R$ {custo_medio:,.2f}" if pd.notna(custo_medio) else "—")

st.divider()

# ---- Tabela de resultados ----
st.subheader("Resultados cruzados")

colunas_exibir = {
    "NM_URNA_CANDIDATO": "Candidato",
    "SG_PARTIDO": "Partido",
    "SG_UF": "UF",
    "QT_VOTOS_TOTAL": "Votos",
    "VR_DESPESA_TOTAL": "Despesa (R$)",
    "CUSTO_POR_VOTO": "Custo/Voto (R$)"
}

# Verifica quais colunas existem para evitar erros
colunas_presentes = {k: v for k, v in colunas_exibir.items() if k in dados_filtrados.columns}

tabela = (
    dados_filtrados[list(colunas_presentes.keys())]
    .rename(columns=colunas_presentes)
    .sort_values("Custo/Voto (R$)", ascending=False)
)

st.dataframe(
    tabela,
    width="stretch",
    hide_index=True,
    column_config={
        "Despesa (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Custo/Voto (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Votos": st.column_config.NumberColumn(format="%d")
    },
)

st.download_button(
    "⬇️ Baixar tabela filtrada",
    data=tabela.to_csv(index=False, sep=";").encode("latin1"),
    file_name="eleicoes_2022.csv",
    mime="text/csv",
)

st.divider()

# ---- Mapa do Brasil ----
st.subheader("🗺️ Calor: Custo Médio por Voto nos Estados")

mapa_dados = dados_filtrados.groupby("SG_UF", as_index=False).agg(
    VR_DESPESA_TOTAL=("VR_DESPESA_TOTAL", "sum"),
    QT_VOTOS_TOTAL=("QT_VOTOS_TOTAL", "sum")
)
mapa_dados["CUSTO_MEDIO_UF"] = mapa_dados["VR_DESPESA_TOTAL"] / mapa_dados["QT_VOTOS_TOTAL"].replace(0, pd.NA)

fig_mapa = px.choropleth(
    mapa_dados,
    geojson=geojson_brasil,
    locations="SG_UF",
    featureidkey="properties.sigla",
    color="CUSTO_MEDIO_UF",
    color_continuous_scale="Reds",
    title="Custo Médio do Voto (R$) por Estado",
    labels={"CUSTO_MEDIO_UF": "Custo/Voto (R$)", "SG_UF": "Estado"}
)
fig_mapa.update_geos(fitbounds="locations", visible=False)
fig_mapa.update_layout(margin={"r":0,"t":40,"l":0,"b":0}, dragmode=False)

st.plotly_chart(fig_mapa, width="stretch", config=CONFIG_GRAFICOS)

st.divider()

# ---- Rankings de Custo por Voto ----
st.subheader("🏆 Rankings: Custo por Voto")

col_rank1, col_rank2 = st.columns(2)

top10_caros = dados_filtrados.sort_values("CUSTO_POR_VOTO", ascending=False).head(10)
fig_caros = px.bar(
    top10_caros,
    x="CUSTO_POR_VOTO",
    y="NM_URNA_CANDIDATO",
    orientation="h", 
    title="Top 10: Votos Mais Caros",
    labels={"NM_URNA_CANDIDATO": "", "CUSTO_POR_VOTO": "Custo (R$)"},
    color_discrete_sequence=["#EF553B"]
)
fig_caros.update_layout(
    yaxis=dict(categoryorder='total ascending', fixedrange=True),
    xaxis=dict(fixedrange=True), 
    yaxis_title=None, 
    dragmode=False
)
col_rank1.plotly_chart(fig_caros, width="stretch", config=CONFIG_GRAFICOS)

dados_validos = dados_filtrados[dados_filtrados["CUSTO_POR_VOTO"] > 0]
top10_baratos = dados_validos.sort_values("CUSTO_POR_VOTO", ascending=True).head(10)
fig_baratos = px.bar(
    top10_baratos,
    x="CUSTO_POR_VOTO",
    y="NM_URNA_CANDIDATO",
    orientation="h",
    title="Top 10: Votos Mais Baratos",
    labels={"NM_URNA_CANDIDATO": "", "CUSTO_POR_VOTO": "Custo (R$)"},
    color_discrete_sequence=["#00CC96"]
)
fig_baratos.update_layout(
    yaxis=dict(categoryorder='total descending', fixedrange=True),
    xaxis=dict(fixedrange=True), 
    yaxis_title=None, 
    dragmode=False
)
col_rank2.plotly_chart(fig_baratos, width="stretch", config=CONFIG_GRAFICOS)

st.divider()

# ---- Gráficos Originais ----
st.subheader("Análise Visual de Gastos")

gasto_por_partido = (
    dados_filtrados.groupby("SG_PARTIDO", as_index=False)["VR_DESPESA_TOTAL"]
    .sum()
    .sort_values("VR_DESPESA_TOTAL", ascending=False)
)

fig_partido = px.bar(
    gasto_por_partido,
    x="SG_PARTIDO",
    y="VR_DESPESA_TOTAL",
    title="Gasto Total por Partido",
    labels={"SG_PARTIDO": "Partido", "VR_DESPESA_TOTAL": "Gasto Total (R$)"},
)
fig_partido.update_layout(xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True), dragmode=False)
st.plotly_chart(fig_partido, width="stretch", config=CONFIG_GRAFICOS)

with st.expander("ℹ️ Notas metodológicas"):
    st.markdown(
        """
        - **Dados consolidados:** Este painel consome uma base de dados já processada (`dados_limpos.csv`) contendo apenas os candidatos eleitos a Deputado Federal em 2022.
        - **Despesas e Votos:** Cruzamento realizado utilizando o identificador único `SQ_CANDIDATO` fornecido pelo TSE.
        - **População:** Utilizados dados do Censo Demográfico de 2022 (IBGE).
        """
    )
