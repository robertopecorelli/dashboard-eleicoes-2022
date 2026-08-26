"""
Dashboard Eleições 2022 — Deputados Federais Eleitos
Cruzamento: Despesas de Campanha (TSE) x Votação (TSE) x População (IBGE)
"""

import os
import pandas as pd
import plotly.express as px
import streamlit as st

# ----------------------------------------------------------------------------
# Configuração (Atualizado para o Streamlit Cloud / GitHub)
# ----------------------------------------------------------------------------
CARGO_FILTRO = "DEPUTADO FEDERAL"
CAMINHO_DADOS_LIMPOS = "dados_limpos.csv"

st.set_page_config(
    page_title="Dashboard Eleições 2022 - Custo por Voto",
    layout="wide",
)

# ----------------------------------------------------------------------------
# Carga de dados - Lendo direto do arquivo limpo no GitHub
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="Carregando dados...")
def carregar_dados() -> pd.DataFrame:
    if os.path.exists(CAMINHO_DADOS_LIMPOS):
        return pd.read_csv(CAMINHO_DADOS_LIMPOS, sep=";", encoding="latin1")
    else:
        raise FileNotFoundError("Arquivo dados_limpos.csv não encontrado no repositório.")

# ----------------------------------------------------------------------------
# App principal
# ----------------------------------------------------------------------------
st.title("Dashboard Eleições 2022 - Deputados Federais Eleitos")
st.caption("Cruzamento de Despesas de Campanha (TSE), Votação (TSE) e População (IBGE)")

try:
    dados = carregar_dados()
except FileNotFoundError as e:
    st.error(
        "Não encontrei o arquivo `dados_limpos.csv` no seu GitHub. "
        "Certifique-se de que você fez o upload desse arquivo no repositório.\n\n"
        f"Detalhe: {e}"
    )
    st.stop()

if dados.empty:
    st.warning("Nenhum registro encontrado para o cargo/situação filtrados.")
    st.stop()

st.caption("📦 Usando cache pré-processado: `dados_limpos.csv`")

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
col1.metric("Candidatos eleitos", f"{dados_filtrados['SQ_CANDIDATO'].nunique():,}".replace(",", "."))
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
    "POPULACAO": "População UF",
    "CUSTO_POR_VOTO": "Custo/Voto (R$)",
    "CUSTO_POR_HABITANTE": "Custo/Habitante (R$)",
}

tabela = (
    dados_filtrados[list(colunas_exibir.keys())]
    .rename(columns=colunas_exibir)
    .sort_values("Custo/Voto (R$)", ascending=False)
)

# Atualizado para o padrão 2026 (width="stretch")
st.dataframe(
    tabela,
    width="stretch",
    hide_index=True,
    column_config={
        "Despesa (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Custo/Voto (R$)": st.column_config.NumberColumn(format="R$ %.4f"),
        "Custo/Habitante (R$)": st.column_config.NumberColumn(format="R$ %.6f"),
        "Votos": st.column_config.NumberColumn(format="%d"),
        "População UF": st.column_config.NumberColumn(format="%d"),
    },
)

st.download_button(
    "⬇️ Baixar tabela filtrada (CSV)",
    data=tabela.to_csv(index=False, sep=";").encode("latin1"),
    file_name="cruzamento_eleicoes_2022.csv",
    mime="text/csv",
)

st.divider()

# ---- Análise Visual de Gastos ----
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
# Atualizado para o padrão 2026
st.plotly_chart(fig_partido, width="stretch")

gasto_por_uf = (
    dados_filtrados.groupby("SG_UF", as_index=False)["VR_DESPESA_TOTAL"]
    .sum()
    .sort_values("VR_DESPESA_TOTAL", ascending=False)
)

fig_uf = px.bar(
    gasto_por_uf,
    x="SG_UF",
    y="VR_DESPESA_TOTAL",
    title="Gasto Total por Estado (UF)",
    labels={"SG_UF": "UF", "VR_DESPESA_TOTAL": "Gasto Total (R$)"},
)
# Atualizado para o padrão 2026
st.plotly_chart(fig_uf, width="stretch")
st.divider()

# ---- Rankings de Custo por Voto ----
st.subheader("🏆 Rankings: Custo por Voto")

# Cria duas colunas para os gráficos ficarem lado a lado
col_rank1, col_rank2 = st.columns(2)

# 1. Top 10 Votos Mais Caros
top10_caros = dados_filtrados.sort_values("CUSTO_POR_VOTO", ascending=False).head(10)
fig_caros = px.bar(
    top10_caros,
    x="CUSTO_POR_VOTO",
    y="NM_URNA_CANDIDATO",
    orientation="h", 
    title="Top 10: Voto Mais Caro",
    labels={"NM_URNA_CANDIDATO": "", "CUSTO_POR_VOTO": "Custo por Voto (R$)"},
    color_discrete_sequence=["#EF553B"] # Vermelho
)
# Ordena o gráfico para o maior ficar no topo
fig_caros.update_layout(yaxis={'categoryorder':'total ascending'})
col_rank1.plotly_chart(fig_caros, width="stretch")

# 2. Top 10 Votos Mais Baratos (Ignorando custo R$ 0)
dados_validos = dados_filtrados[dados_filtrados["CUSTO_POR_VOTO"] > 0]
top10_baratos = dados_validos.sort_values("CUSTO_POR_VOTO", ascending=True).head(10)
fig_baratos = px.bar(
    top10_baratos,
    x="CUSTO_POR_VOTO",
    y="NM_URNA_CANDIDATO",
    orientation="h",
    title="Top 10: Voto Mais Barato",
    labels={"NM_URNA_CANDIDATO": "", "CUSTO_POR_VOTO": "Custo por Voto (R$)"},
    color_discrete_sequence=["#00CC96"] # Verde
)
# Ordena o gráfico para o menor ficar no topo
fig_baratos.update_layout(yaxis={'categoryorder':'total descending'})
col_rank2.plotly_chart(fig_baratos, width="stretch")
with st.expander("ℹ️ Notas metodológicas"):
    st.markdown(
        """
        - **Dados consolidados:** Este painel consome uma base de dados já processada (`dados_limpos.csv`) contendo apenas os candidatos eleitos a Deputado Federal em 2022.
        - **Despesas e Votos:** Cruzamento realizado utilizando o identificador único `SQ_CANDIDATO` fornecido pelo TSE.
        - **População:** Utilizados dados do Censo Demográfico de 2022 (IBGE).
        """
    )
