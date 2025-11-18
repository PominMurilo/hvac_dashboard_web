import pandas as pd
import plotly.express as px
import streamlit as st

# =========================
# 1. CONFIGURAÇÃO BÁSICA
# =========================
st.set_page_config(
    page_title="Dashboard HVAC com IA",
    layout="wide",
)

st.title("Dashboard HVAC com IA")
st.markdown(
    """
    Este dashboard usa **dados reais de um sistema HVAC** e um **modelo de IA** para analisar:
    - Consumo de energia (kWh) e custo estimado (R$);
    - Comportamento de operação ao longo do tempo;
    - Diferença entre potência real e potência prevista;
    - Cenários de economia baseados em regras operacionais simples.
    """
)

TARIFA_KWH = 0.80  # tarifa usada para cálculo de custo

# =========================
# 2. CARREGAR DADOS
# =========================
@st.cache_data
def load_data():
    base = pd.read_csv("hvac_dashboard_base.csv")

    # Garantir timestamp como datetime
    base["timestamp"] = pd.to_datetime(base["timestamp"])

    # Garantir coluna date como date (não string)
    if "date" in base.columns:
        base["date"] = pd.to_datetime(base["date"]).dt.date
    else:
        base["date"] = base["timestamp"].dt.date

    # Garantir coluna year_month (AAAA-MM) como string
    if "year_month" in base.columns:
        base["year_month"] = base["year_month"].astype(str)
    else:
        base["year_month"] = base["timestamp"].dt.strftime("%Y-%m")

    # Garantir que is_business_hours e is_weekend sejam inteiros 0/1
    if "is_business_hours" in base.columns:
        base["is_business_hours"] = base["is_business_hours"].astype(int)
    if "is_weekend" in base.columns:
        base["is_weekend"] = base["is_weekend"].astype(int)

    return base


df_base = load_data()

# =========================
# 3. CENÁRIOS (cálculo no período inteiro)
# =========================
@st.cache_data
def compute_scenarios(base: pd.DataFrame):
    """
    Calcula dois cenários simples usando a energia real (energy_5min_real_kWh)
    no período completo disponível (jun–ago/2022).

    Cenário 1: desligar 1h antes do último on/off de cada dia.
    Cenário 2: sistema ligado apenas em horário comercial.
    """
    base = base.copy()
    total_base_kWh = base["energy_5min_real_kWh"].sum()

    # -------- Cenário 1: desligar 1h antes --------
    s1 = base.copy()
    s1["energy_s1_kWh"] = s1["energy_5min_real_kWh"]

    for current_date, idx in s1.groupby("date").groups.items():
        day_mask = s1.index.isin(idx)
        mask_on = day_mask & (s1["on_off"] == 1)
        if not mask_on.any():
            continue

        last_time = s1.loc[mask_on, "timestamp"].max()
        cutoff = last_time - pd.Timedelta(hours=1)

        mask_early_off = (
            mask_on
            & (s1["timestamp"] > cutoff)
            & (s1["timestamp"] <= last_time)
        )

        # Zera energia no cenário (como se tivesse desligado nessa hora final)
        s1.loc[mask_early_off, "energy_s1_kWh"] = 0.0

    total_s1_kWh = s1["energy_s1_kWh"].sum()
    economia1_kWh = total_base_kWh - total_s1_kWh

    daily_s1 = (
        s1.groupby("date")
        .agg(
            energy_base_kWh=("energy_5min_real_kWh", "sum"),
            energy_s1_kWh=("energy_s1_kWh", "sum"),
        )
        .reset_index()
    )
    daily_s1["economia_kWh"] = daily_s1["energy_base_kWh"] - daily_s1["energy_s1_kWh"]
    economia1_media_dia = daily_s1["economia_kWh"].mean()

    # -------- Cenário 2: só horário comercial --------
    s2 = base.copy()
    s2["energy_s2_kWh"] = s2["energy_5min_real_kWh"]

    mask_off_hours_all = s2["is_business_hours"] == 0
    s2.loc[mask_off_hours_all, "energy_s2_kWh"] = 0.0

    total_s2_kWh = s2["energy_s2_kWh"].sum()
    economia2_kWh = total_base_kWh - total_s2_kWh

    daily_s2 = (
        s2.groupby("date")
        .agg(
            energy_base_kWh=("energy_5min_real_kWh", "sum"),
            energy_s2_kWh=("energy_s2_kWh", "sum"),
        )
        .reset_index()
    )
    daily_s2["economia_kWh"] = daily_s2["energy_base_kWh"] - daily_s2["energy_s2_kWh"]
    economia2_media_dia = daily_s2["economia_kWh"].mean()

    return {
        "total_base_kWh": total_base_kWh,
        "s1_total_kWh": total_s1_kWh,
        "s1_economia_kWh": economia1_kWh,
        "s1_economia_media_dia": economia1_media_dia,
        "s1_daily": daily_s1,
        "s2_total_kWh": total_s2_kWh,
        "s2_economia_kWh": economia2_kWh,
        "s2_economia_media_dia": economia2_media_dia,
        "s2_daily": daily_s2,
    }


scenario_stats = compute_scenarios(df_base)

# =========================
# 4. SIDEBAR - FILTROS (para as abas 1 e 2)
# =========================
st.sidebar.header("Filtros")

min_date = df_base["date"].min()
max_date = df_base["date"].max()

date_range = st.sidebar.date_input(
    "Período analisado",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(date_range, tuple):
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

# Filtro de horário comercial (para as abas de operação/energia)
business_mode = st.sidebar.radio(
    "Horário comercial?",
    options=["Todos", "Só comercial", "Só fora do comercial"],
)

if business_mode == "Todos":
    business_vals = [0, 1]
elif business_mode == "Só comercial":
    business_vals = [1]
else:  # Só fora do comercial
    business_vals = [0]

# Filtro de fim de semana
weekend_mode = st.sidebar.radio(
    "Fim de semana?",
    options=["Todos", "Só dias úteis", "Só fim de semana"],
)

if weekend_mode == "Todos":
    weekend_vals = [0, 1]
elif weekend_mode == "Só dias úteis":
    weekend_vals = [0]
else:  # Só fim de semana
    weekend_vals = [1]

mask = (
    (df_base["date"] >= start_date)
    & (df_base["date"] <= end_date)
    & (df_base["is_business_hours"].isin(business_vals))
    & (df_base["is_weekend"].isin(weekend_vals))
)
df_base_filt = df_base[mask].copy()

if df_base_filt.empty:
    st.warning("Nenhum dado encontrado para os filtros selecionados.")
    st.stop()

# =========================
# 5. KPI DIÁRIO E MENSAL A PARTIR DO BASE FILTRADO
# =========================
df_daily = (
    df_base_filt.groupby("date")
    .agg(
        daily_energy_kWh=("energy_5min_real_kWh", "sum"),
        daily_avg_power=("active_power_real", "mean"),
    )
    .reset_index()
)
df_daily["daily_cost"] = df_daily["daily_energy_kWh"] * TARIFA_KWH

df_monthly = (
    df_base_filt.groupby("year_month")
    .agg(
        monthly_energy_kWh=("energy_5min_real_kWh", "sum"),
    )
    .reset_index()
)
df_monthly["monthly_cost"] = df_monthly["monthly_energy_kWh"] * TARIFA_KWH

# =========================
# 6. SELEÇÃO DE ABA
# =========================
aba = st.radio(
    "Selecione a visão",
    ["Visão geral de energia", "Operação & IA", "Cenários de IA"],
    horizontal=True,
)

# =========================
# 7. VISÃO GERAL DE ENERGIA
# =========================
if aba == "Visão geral de energia":
    st.subheader("Resumo energético do período selecionado")

    total_energy = df_daily["daily_energy_kWh"].sum()
    total_cost = df_daily["daily_cost"].sum()
    media_diaria = df_daily["daily_energy_kWh"].mean()

    col1, col2, col3 = st.columns(3)
    col1.metric("Energia total (kWh)", f"{total_energy:,.1f}")
    col2.metric("Custo total estimado (R$)", f"{total_cost:,.2f}")
    col3.metric("Consumo médio diário (kWh/dia)", f"{media_diaria:,.1f}")

    st.markdown("---")

    col_g1, col_g2 = st.columns(2)

    # Gráfico de energia diária
    with col_g1:
        st.markdown("#### Energia diária (kWh)")
        fig_daily = px.line(
            df_daily,
            x="date",
            y="daily_energy_kWh",
            labels={"date": "Data", "daily_energy_kWh": "Energia (kWh)"},
        )
        st.plotly_chart(fig_daily, use_container_width=True)

    # Gráfico de energia mensal
    with col_g2:
        st.markdown("#### Energia mensal (kWh)")
        if not df_monthly.empty:
            fig_month = px.bar(
                df_monthly,
                x="year_month",
                y="monthly_energy_kWh",
                labels={"year_month": "Ano-Mês", "monthly_energy_kWh": "Energia (kWh)"},
            )
            st.plotly_chart(fig_month, use_container_width=True)
        else:
            st.info("Nenhum dado mensal disponível no período selecionado.")

    st.markdown("#### Custo mensal estimado (R$)")
    if not df_monthly.empty:
        fig_cost = px.bar(
            df_monthly,
            x="year_month",
            y="monthly_cost",
            labels={"year_month": "Ano-Mês", "monthly_cost": "Custo (R$)"},
        )
        st.plotly_chart(fig_cost, use_container_width=True)
    else:
        st.info("Nenhum dado mensal disponível no período selecionado.")

# =========================
# 8. VISÃO DE OPERAÇÃO & IA
# =========================
elif aba == "Operação & IA":
    st.subheader("Operação do HVAC vs Previsão da IA")

    st.markdown(
        """
        Aqui comparamos a **potência ativa real** com a **potência prevista pela IA**.
        Quando a curva real fica muito acima da prevista, isso pode indicar **ineficiência ou anomalia**
        (porta aberta, filtro sujo, carga térmica atípica, etc.).
        """
    )

    st.markdown("##### Zoom de datas para visualização detalhada")
    min_ts = df_base_filt["timestamp"].min()
    max_ts = df_base_filt["timestamp"].max()

    zoom_range = st.slider(
        "Selecione um intervalo de datas para o gráfico de linha",
        min_value=min_ts.to_pydatetime(),
        max_value=max_ts.to_pydatetime(),
        value=(min_ts.to_pydatetime(), max_ts.to_pydatetime()),
    )

    mask_zoom = (
        (df_base_filt["timestamp"] >= zoom_range[0])
        & (df_base_filt["timestamp"] <= zoom_range[1])
    )
    df_zoom = df_base_filt[mask_zoom].copy()

    st.markdown("#### Potência ativa – real vs prevista (kW)")
    if not df_zoom.empty:
        fig_power = px.line(
            df_zoom,
            x="timestamp",
            y=["active_power_real", "active_power_pred"],
            labels={
                "timestamp": "Tempo",
                "value": "Potência (kW)",
                "variable": "Série",
            },
        )
        st.plotly_chart(fig_power, use_container_width=True)
    else:
        st.info("Nenhum dado no intervalo selecionado.")

    st.markdown("---")

    st.markdown("#### Potência vs Temperatura externa")
    if not df_base_filt.empty:
        df_sample = df_base_filt
        if len(df_sample) > 5000:
            df_sample = df_sample.sample(5000, random_state=42)

        fig_scatter = px.scatter(
            df_sample,
            x="outside_temp",
            y="active_power_real",
            color="is_business_hours",
            labels={
                "outside_temp": "Temperatura externa (°C)",
                "active_power_real": "Potência real (kW)",
                "is_business_hours": "Horário comercial (0/1)",
            },
            title="Potência real vs temperatura externa (colorido por horário comercial)",
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
    else:
        st.info("Nenhum dado disponível para o scatter.")

# =========================
# 9. ABA CENÁRIOS DE IA
# =========================
else:
    st.subheader("Cenários de operação simulados")

    st.markdown(
        """
        Nesta aba, mostramos dois cenários simples de economia calculados sobre
        **todo o período de dados (jun–ago/2022)**, usando as leituras reais de energia
        (`energy_5min_real_kWh`):
        
        1. **Desligar 1h antes** do último horário em que o sistema esteve ligado a cada dia.
        2. **Operar apenas em horário comercial**, desligando o sistema fora do horário útil.
        
        Essas simulações foram inspiradas
        pelo modelo de IA, que aprendeu o comportamento típico do sistema e orienta quais
        mudanças de regra fazem sentido testar.
        """
    )

    total_base = scenario_stats["total_base_kWh"]

    # ----- Cenário 1 -----
    s1_total = scenario_stats["s1_total_kWh"]
    s1_econ = scenario_stats["s1_economia_kWh"]
    s1_econ_med = scenario_stats["s1_economia_media_dia"]
    s1_econ_rs = s1_econ * TARIFA_KWH
    s1_pct = (s1_econ / total_base * 100) if total_base > 0 else 0.0

    st.markdown("### Cenário 1 – Desligar 1h antes do último on/off de cada dia")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Consumo original (kWh)", f"{total_base:,.1f}")
    c2.metric("Consumo no cenário (kWh)", f"{s1_total:,.1f}")
    c3.metric("Economia total (kWh)", f"{s1_econ:,.1f}")
    c4.metric("Economia total (R$)", f"{s1_econ_rs:,.2f}")

    c5, c6 = st.columns(2)
    c5.metric("Economia média (kWh/dia)", f"{s1_econ_med:,.2f}")
    c6.metric("Redução percentual", f"{s1_pct:,.3f}%")

    st.markdown("#### Economia diária – Cenário 1")
    s1_daily = scenario_stats["s1_daily"]
    fig_s1 = px.bar(
        s1_daily,
        x="date",
        y="economia_kWh",
        labels={"date": "Data", "economia_kWh": "Economia (kWh)"},
    )
    st.plotly_chart(fig_s1, use_container_width=True)

    st.markdown("---")

    # ----- Cenário 2 -----
    s2_total = scenario_stats["s2_total_kWh"]
    s2_econ = scenario_stats["s2_economia_kWh"]
    s2_econ_med = scenario_stats["s2_economia_media_dia"]
    s2_econ_rs = s2_econ * TARIFA_KWH
    s2_pct = (s2_econ / total_base * 100) if total_base > 0 else 0.0

    st.markdown("### Cenário 2 – HVAC ligado apenas em horário comercial")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Consumo original (kWh)", f"{total_base:,.1f}")
    d2.metric("Consumo no cenário (kWh)", f"{s2_total:,.1f}")
    d3.metric("Economia total (kWh)", f"{s2_econ:,.1f}")
    d4.metric("Economia total (R$)", f"{s2_econ_rs:,.2f}")

    d5, d6 = st.columns(2)
    d5.metric("Economia média (kWh/dia)", f"{s2_econ_med:,.2f}")
    d6.metric("Redução percentual", f"{s2_pct:,.3f}%")

    st.markdown("#### Economia diária – Cenário 2")
    s2_daily = scenario_stats["s2_daily"]
    fig_s2 = px.bar(
        s2_daily,
        x="date",
        y="economia_kWh",
        labels={"date": "Data", "economia_kWh": "Economia (kWh)"},
    )
    st.plotly_chart(fig_s2, use_container_width=True)
