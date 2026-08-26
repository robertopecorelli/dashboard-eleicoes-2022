"""
Dashboard Eleições 2022 — Deputados Federais Eleitos
Cruzamento: Despesas de Campanha (TSE) x Votação (TSE) x População (IBGE)

Arquitetura anti-timeout / anti-estouro de memória:
    - Na primeira execução, processa os CSVs originais (despesas.csv e votos.csv,
      que podem ter GBs) usando `usecols` para ler só as colunas necessárias.
    - O votos.csv (o arquivo gigante, ~2GB) é lido em pedaços (`chunksize=100000`)
      em vez de ser carregado inteiro na memória: a cada pedaço, filtra só
      Deputado Federal eleito e guarda o resultado (já bem menor) numa lista;
      no final, concatena tudo com `pd.concat()`.
    - Depois cruza com despesas e IBGE, calcula os custos e SALVA o resultado
      em dados_limpos.csv (arquivo pequeno).
    - Nas execuções seguintes, o app detecta que dados_limpos.csv já existe e
      NUNCA mais toca nos arquivos gigantes — só lê o CSV limpo. Isso evita o
      Erro 502 por timeout e o travamento silencioso por falta de RAM no Colab.

Como rodar no Google Colab:
    1. Monte o Drive:
        from google.colab import drive
        drive.mount('/content/drive')
    2. Instale as dependências:
        !pip install streamlit -q
    3. Como o Colab não expõe portas HTTP diretamente, use um túnel, ex.:
        !npm install -g localtunnel
        !streamlit run app.py &>/content/logs.txt &
        !npx localtunnel --port 8501
    (ou use pyngrok como alternativa ao localtunnel)

    Se algum dia precisar reprocessar do zero (ex.: dados do TSE atualizados),
    basta apagar dados_limpos.csv da pasta do Drive e rodar de novo.
"""

import os
import pandas as pd
import plotly.express as px
import streamlit as st

# ----------------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------------
BASE_PATH = "/content/drive/MyDrive/dashboard-eleicoes/"
CARGO_FILTRO = "DEPUTADO FEDERAL"

CAMINHO_DESPESAS = BASE_PATH + "despesas.csv"
CAMINHO_VOTOS = BASE_PATH + "votos.csv"
CAMINHO_DADOS_LIMPOS = BASE_PATH + "dados_limpos.csv"

# Só as colunas que realmente usamos — evita carregar o CSV de votos (2GB)
# inteiro na memória.
COLS_DESPESAS = ["SQ_CANDIDATO", "DS_CARGO", "VR_DESPESA_CONTRATADA"]
COLS_VOTOS = [
    "SQ_CANDIDATO",
    "NR_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "SG_UF",
    "SG_PARTIDO",
    "NM_PARTIDO",
    "DS_CARGO",
    "DS_SIT_TOT_TURNO",
    "QT_VOTOS_NOMINAIS",
]

st.set_page_config(
    page_title="Dashboard Eleições 2022 - Custo por Voto",
    layout="wide",
)

# ----------------------------------------------------------------------------
# Processamento pesado — só roda quando dados_limpos.csv ainda não existe
# ----------------------------------------------------------------------------
def processar_do_zero() -> pd.DataFrame:
    """Lê os CSVs originais (grandes), filtra, cruza e devolve o dataframe final.
    Só é chamada quando dados_limpos.csv ainda não existe no Drive."""

    with st.spinner("Primeira execução: lendo e processando os arquivos originais (pode demorar)..."):
        despesas = pd.read_csv(
            CAMINHO_DESPESAS,
            sep=";",
            encoding="latin1",
            usecols=COLS_DESPESAS,
            low_memory=False,
        )
        # --- IBGE: população por UF (Censo Demográfico 2022) ---
        # O arquivo ibge.csv foi abandonado por estar com a formatação
        # corrompida (nomes/colunas inconsistentes). Em vez de depender dele,
        # os dados de população das 27 unidades federativas são declarados
        # diretamente no código, com base no Censo 2022 do IBGE.
        ibge = pd.DataFrame(
            {
                "SG_UF": [
                    "SP", "MG", "RJ", "BA", "PR", "RS", "PE", "CE", "PA", "SC",
                    "GO", "MA", "PB", "AM", "ES", "MT", "RN", "PI", "AL", "DF",
                    "MS", "SE", "RO", "TO", "AC", "AP", "RR",
                ],
                "POPULACAO": [
                    44420459, 20538718, 16054524, 14136417, 11443208, 10880506,
                    9058155, 8791688, 8116132, 7609601, 7055228, 6775152,
                    3974495, 3941175, 3833486, 3658813, 3302729, 3269200,
                    3127511, 2817068, 2756700, 2209558, 1581016, 1511459,
                    830026, 733508, 636303,
                ],
            }
        )

        # --- Normaliza valor de despesa (TSE costuma usar vírgula decimal) ---
        if despesas["VR_DESPESA_CONTRATADA"].dtype == object:
            despesas["VR_DESPESA_CONTRATADA"] = (
                despesas["VR_DESPESA_CONTRATADA"]
                .astype(str)
                .str.replace(".", "", regex=False)   # remove separador de milhar, se houver
                .str.replace(",", ".", regex=False)   # vírgula -> ponto decimal
                .astype(float)
            )

        # --- 1) Filtra DESPESAS para o cargo alvo e agrega por candidato ---
        despesas_cargo = despesas[despesas["DS_CARGO"].str.upper() == CARGO_FILTRO]
        despesas_agg = despesas_cargo.groupby("SQ_CANDIDATO", as_index=False).agg(
            VR_DESPESA_TOTAL=("VR_DESPESA_CONTRATADA", "sum")
        )
        del despesas, despesas_cargo  # libera memória o quanto antes

        # --- 2) Lê VOTOS em pedaços (chunks) para não estourar a RAM ---
        # votos.csv pode ter ~2GB; em vez de carregar tudo de uma vez,
        # lemos em blocos de 100.000 linhas, filtramos cada bloco (cargo alvo
        # + situação "eleito") e guardamos só o resultado, já bem menor.
        TAMANHO_CHUNK = 100_000
        chunks_filtrados = []

        leitor_votos = pd.read_csv(
            CAMINHO_VOTOS,
            sep=";",
            encoding="latin1",
            usecols=COLS_VOTOS,
            low_memory=False,
            chunksize=TAMANHO_CHUNK,
        )

        for chunk in leitor_votos:
            chunk_filtrado = chunk[
                (chunk["DS_CARGO"].str.upper() == CARGO_FILTRO)
                & (chunk["DS_SIT_TOT_TURNO"].str.upper().str.contains("ELEITO", na=False))
            ]
            if not chunk_filtrado.empty:
                chunks_filtrados.append(chunk_filtrado)

        votos_eleitos = pd.concat(chunks_filtrados, ignore_index=True)
        del chunks_filtrados  # libera a lista de chunks assim que possível

        # Dados cadastrais (1 linha por candidato — são constantes entre as
        # linhas de zona/município)
        candidatos = votos_eleitos.drop_duplicates(subset="SQ_CANDIDATO")[
            [
                "SQ_CANDIDATO",
                "NR_CANDIDATO",
                "NM_CANDIDATO",
                "NM_URNA_CANDIDATO",
                "SG_UF",
                "SG_PARTIDO",
                "NM_PARTIDO",
                "DS_SIT_TOT_TURNO",
            ]
        ]

        # Total de votos nominais por candidato (soma entre zonas/municípios)
        votos_agg = votos_eleitos.groupby("SQ_CANDIDATO", as_index=False).agg(
            QT_VOTOS_TOTAL=("QT_VOTOS_NOMINAIS", "sum")
        )
        del votos_eleitos

        base = candidatos.merge(votos_agg, on="SQ_CANDIDATO", how="left")

        # --- 3) Merge com despesas (chave: SQ_CANDIDATO) ---
        base = base.merge(despesas_agg, on="SQ_CANDIDATO", how="left")
        base["VR_DESPESA_TOTAL"] = base["VR_DESPESA_TOTAL"].fillna(0)

        # --- 4) Merge com IBGE (chave: SG_UF) ---
        ibge["POPULACAO"] = pd.to_numeric(ibge["POPULACAO"], errors="coerce")
        base = base.merge(ibge[["SG_UF", "POPULACAO"]], on="SG_UF", how="left")

        # --- 5) Métricas ---
        base["CUSTO_POR_VOTO"] = base["VR_DESPESA_TOTAL"] / base["QT_VOTOS_TOTAL"].replace(0, pd.NA)
        base["CUSTO_POR_HABITANTE"] = base["VR_DESPESA_TOTAL"] / base["POPULACAO"].replace(0, pd.NA)

        # --- 6) Salva o resultado enxuto para as próximas execuções ---
        base.to_csv(CAMINHO_DADOS_LIMPOS, sep=";", index=False, encoding="latin1")

    return base


# ----------------------------------------------------------------------------
# Carga de dados — decide entre ler o cache em disco ou reprocessar do zero
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="Carregando dados...")
def carregar_dados() -> pd.DataFrame:
    if os.path.exists(CAMINHO_DADOS_LIMPOS):
        # Caminho rápido: arquivo pequeno, já pronto — não toca nos originais
        return pd.read_csv(CAMINHO_DADOS_LIMPOS, sep=";", encoding="latin1")

    # Caminho lento: só acontece uma vez, na primeira execução
    return processar_do_zero()


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
st.title("Dashboard Eleições 2022 - Deputados Federais Eleitos")
st.caption("Cruzamento de Despesas de Campanha (TSE), Votação (TSE) e População (IBGE)")

try:
    dados = carregar_dados()
except FileNotFoundError as e:
    st.error(
        "Não encontrei os arquivos necessários em "
        f"`{BASE_PATH}`. Confirme se o Google Drive foi montado "
        "(`drive.mount('/content/drive')`) e se despesas.csv e votos.csv "
        "estão nessa pasta (necessários apenas na primeira execução, "
        "antes de dados_limpos.csv existir).\n\n"
        f"Detalhe: {e}"
    )
    st.stop()

if dados.empty:
    st.warning("Nenhum registro encontrado para o cargo/situação filtrados.")
    st.stop()

if os.path.exists(CAMINHO_DADOS_LIMPOS):
    st.caption(f"📦 Usando cache pré-processado: `dados_limpos.csv`")

# ---- Sidebar: filtros ----
st.sidebar.header("Filtros")

ufs_disponiveis = sorted(dados["SG_UF"].dropna().unique())
uf_selecionadas = st.sidebar.multiselect("Estado (UF)", ufs_disponiveis, default=ufs_disponiveis)

partidos_disponiveis = sorted(dados["SG_PARTIDO"].dropna().unique())
partidos_selecionados = st.sidebar.multiselect(
    "Partido", partidos_disponiveis, default=partidos_disponiveis
)

if st.sidebar.button("🔄 Reprocessar dados originais"):
    if os.path.exists(CAMINHO_DADOS_LIMPOS):
        os.remove(CAMINHO_DADOS_LIMPOS)
    st.cache_data.clear()
    st.rerun()

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

st.dataframe(
    tabela,
    use_container_width=True,
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
st.plotly_chart(fig_partido, use_container_width=True)

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
st.plotly_chart(fig_uf, use_container_width=True)

with st.expander("ℹ️ Notas metodológicas"):
    st.markdown(
        """
        - **Cache em disco:** na primeira execução, o app lê despesas.csv e
          votos.csv (potencialmente enormes), processa e salva o resultado em
          `dados_limpos.csv`. Nas execuções seguintes, só esse arquivo pequeno
          é lido — os originais nem são tocados, o que evita o timeout (Erro
          502) no Colab. Use o botão "Reprocessar dados originais" na barra
          lateral se precisar atualizar os dados-fonte.
        - **Leitura seletiva de colunas:** o processamento usa `usecols` para
          carregar só as colunas necessárias dos CSVs originais, reduzindo o
          uso de memória.
        - **Leitura em chunks:** o arquivo de votos (o maior, podendo chegar a
          GBs) é lido em blocos de 100.000 linhas (`chunksize=100000`) em vez
          de inteiro de uma vez. Cada bloco é filtrado (cargo + situação
          "eleito") e só o resultado, já pequeno, é mantido em memória — isso
          evita o travamento por falta de RAM no Colab.
        - **População por UF:** os dados de população das 27 unidades
          federativas (Censo Demográfico 2022 do IBGE) estão declarados
          diretamente no código, e não lidos de um CSV externo — o arquivo
          ibge.csv foi abandonado por estar com a formatação corrompida.
        - **Chave de junção despesas × votos:** `SQ_CANDIDATO` (identificador único de
          candidatura no TSE), por ser mais confiável que `NR_CANDIDATO`, que pode se
          repetir entre estados.
        - **Filtro de eleitos:** como Deputado Federal é cargo proporcional, o TSE grava
          a situação como `ELEITO POR QP` ou `ELEITO POR MÉDIA` — por isso o filtro
          verifica se `DS_SIT_TOT_TURNO` **contém** "ELEITO", e não igualdade exata.
        - Candidatos eleitos sem despesa declarada aparecem com despesa = R$ 0,00.
        """
    )
