import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

# =========================
# CONFIGURAÇÃO
# =========================
OLLAMA_URL = "http://localhost:11434/api/generate"
MODELO = "gemma3:1b"  # ex.: gemma3:1b, llama3.1, mistral
LOG_PATH = Path("./logs/interactions.jsonl")

st.set_page_config(
    page_title="FINA+ | Assistente Financeiro",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================
# ESTILO (FINTECH LOOK)
# =========================
st.markdown(
    """
    <style>
        .main > div {padding-top: 1.2rem;}
        .kpi-card {
            background: linear-gradient(135deg, rgba(37,99,235,.12), rgba(16,185,129,.10));
            border: 1px solid rgba(148,163,184,.25);
            border-radius: 14px;
            padding: 14px 16px;
            margin-bottom: 8px;
        }
        .kpi-title {
            font-size: 0.85rem;
            color: #94a3b8;
            margin-bottom: 6px;
        }
        .kpi-value {
            font-size: 1.9rem;
            font-weight: 700;
            line-height: 1.1;
        }
        .badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: .8rem;
            border: 1px solid rgba(148,163,184,.35);
            background: rgba(15,23,42,.35);
            color: #cbd5e1;
        }
        .section-title {
            font-size: 1.05rem;
            font-weight: 600;
            margin: 8px 0 10px 0;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================
# FUNÇÕES AUXILIARES
# =========================
def brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def ensure_log():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.touch()

def save_log(payload: dict):
    ensure_log()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

@st.cache_data
def carregar_dados():
    base = Path("./data")
    perfil = json.load(open(base / "perfil_investidor.json", "r", encoding="utf-8"))
    transacoes = pd.read_csv(base / "transacoes.csv")
    historico = pd.read_csv(base / "historico_atendimento.csv")
    produtos = json.load(open(base / "produtos_financeiros.json", "r", encoding="utf-8"))
    return perfil, transacoes, historico, produtos

def normalizar_transacoes(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    cols = {c.lower().strip(): c for c in d.columns}

    col_valor = cols.get("valor")
    col_tipo = cols.get("tipo")
    col_categoria = cols.get("categoria")
    col_data = cols.get("data")

    # fallback de valor
    if col_valor is None:
        # tenta achar primeira coluna numérica
        num_cols = [c for c in d.columns if pd.api.types.is_numeric_dtype(d[c])]
        if num_cols:
            col_valor = num_cols[0]
        else:
            d["valor"] = 0.0
            col_valor = "valor"

    d[col_valor] = pd.to_numeric(d[col_valor], errors="coerce").fillna(0)

    if col_tipo is None:
        d["tipo"] = "D"
        col_tipo = "tipo"

    if col_categoria is None:
        d["categoria"] = "Sem categoria"
        col_categoria = "categoria"

    if col_data is None:
        d["data"] = pd.NaT
        col_data = "data"

    d[col_data] = pd.to_datetime(d[col_data], errors="coerce", dayfirst=True)

    # normalização de tipo (aceita várias escritas)
    tipo_norm = d[col_tipo].astype(str).str.lower().str.strip()
    is_receita = (
        tipo_norm.str.startswith("r")
        | tipo_norm.str.contains("receita")
        | tipo_norm.str.contains("entrada")
        | tipo_norm.str.contains("credito")
        | tipo_norm.str.contains("crédito")
    )
    is_despesa = (
        tipo_norm.str.startswith("d")
        | tipo_norm.str.contains("despesa")
        | tipo_norm.str.contains("saida")
        | tipo_norm.str.contains("saída")
        | tipo_norm.str.contains("debito")
        | tipo_norm.str.contains("débito")
    )

    d["_valor"] = d[col_valor]
    d["_tipo_receita"] = is_receita
    d["_tipo_despesa"] = is_despesa
    d["_categoria"] = d[col_categoria].astype(str)
    d["_data"] = d[col_data]

    return d

def calcular_kpis(transacoes: pd.DataFrame):
    d = normalizar_transacoes(transacoes)

    receita = d.loc[d["_tipo_receita"], "_valor"].sum()
    despesa = d.loc[d["_tipo_despesa"], "_valor"].sum()

    # fallback: se nada reconhecido, considera tudo despesa
    if receita == 0 and despesa == 0 and len(d) > 0:
        despesa = d["_valor"].sum()

    saldo = receita - despesa
    taxa_poupanca = (saldo / receita * 100) if receita > 0 else 0.0

    top_cat = (
        d.groupby("_categoria")["_valor"]
        .sum()
        .sort_values(ascending=False)
        .head(8)
    )

    return receita, despesa, saldo, taxa_poupanca, top_cat

def detectar_intencao(msg: str) -> str:
    t = msg.lower()

    if any(k in t for k in ["gasto", "despesa", "orçamento", "orcamento", "cartão", "cartao", "fatura", "economizar"]):
        return "saude_financeira"
    if any(k in t for k in ["perfil", "conservador", "moderado", "arrojado", "risco", "suitability"]):
        return "suitability"
    if any(k in t for k in ["comparar", "produto", "cdb", "tesouro", "fundo", "ação", "acao", "investimento"]):
        return "comparacao_produtos"
    if any(k in t for k in ["tempo", "clima", "futebol", "filme", "receita de bolo"]):
        return "fora_escopo"

    return "geral"

def resumo_transacoes(transacoes: pd.DataFrame) -> str:
    receita, despesa, saldo, _, top_cat = calcular_kpis(transacoes)

    top_txt = "\n".join([f"- {cat}: {brl(val)}" for cat, val in top_cat.items()]) if len(top_cat) else "- Sem dados"

    return f"""
Receita total (estimada): {brl(receita)}
Despesa total (estimada): {brl(despesa)}
Saldo estimado: {brl(saldo)}

Top categorias de gasto:
{top_txt}
"""

def montar_contexto(perfil, transacoes, historico, produtos, intencao):
    resumo = resumo_transacoes(transacoes)
    hist_recente = historico.tail(10).to_string(index=False)
    trans_recente = transacoes.tail(20).to_string(index=False)

    contexto = f"""
[PERFIL DO CLIENTE]
Nome: {perfil.get('nome', 'N/A')}
Idade: {perfil.get('idade', 'N/A')}
Perfil de investidor: {perfil.get('perfil_investidor', 'N/A')}
Objetivo principal: {perfil.get('objetivo_principal', 'N/A')}
Patrimônio total: {perfil.get('patrimonio_total', 'N/A')}
Reserva de emergência atual: {perfil.get('reserva_emergencia_atual', 'N/A')}

[RESUMO FINANCEIRO]
{resumo}

[TRANSAÇÕES RECENTES - AMOSTRA]
{trans_recente}

[HISTÓRICO DE ATENDIMENTOS - AMOSTRA]
{hist_recente}

[PRODUTOS FINANCEIROS DISPONÍVEIS]
{json.dumps(produtos, ensure_ascii=False, indent=2)}

[INTENÇÃO DETECTADA]
{intencao}
"""
    return contexto

SYSTEM_PROMPT = """
Você é o FINA+, um assistente de Saúde Financeira e Suitability Educativo.

OBJETIVO:
Ajudar iniciantes a organizar finanças pessoais e entender compatibilidade entre perfil de risco e produtos financeiros, de forma educativa e responsável.

REGRAS OBRIGATÓRIAS:
1) Baseie-se SOMENTE nos dados de contexto fornecidos.
2) Se faltar dado, admita limitação e peça complemento objetivo.
3) NUNCA prometa rentabilidade, lucro garantido ou resultado futuro.
4) NUNCA solicite dados sensíveis (senha, token, CVV, OTP).
5) Não execute operações financeiras.
6) Se a pergunta estiver fora de finanças, diga que seu escopo é finanças e redirecione.
7) Em suitability, respeite perfil do investidor (conservador/moderado/arrojado).
8) Responda em português-BR, linguagem simples, tom profissional e acessível.

EXEMPLO DE ESTILO:
Usuário: "Estou gastando muito no cartão."
Resposta:
Seu padrão de gastos no cartão mostra concentração em despesas variáveis, e isso dificulta manter previsibilidade ao longo do mês. Uma forma prática de começar é definir um teto semanal por categoria — por exemplo, alimentação, transporte e lazer — e ativar alertas de limite no aplicativo. Quando você separa os gastos por categoria, fica mais fácil identificar excessos cedo e evitar acúmulo no fechamento da fatura. Se quiser, eu monto um plano de 4 semanas com metas simples para reduzir sua fatura de forma gradual e realista.
"""

def perguntar_ollama(msg, contexto):
    prompt = f"""
{SYSTEM_PROMPT}

[CONTEXTO]
{contexto}

[PERGUNTA DO USUÁRIO]
{msg}
"""

    payload = {"model": MODELO, "prompt": prompt, "stream": False}

    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        return data.get("response", "Não consegui gerar resposta agora."), "ok"
    except requests.exceptions.ConnectionError:
        return (
            "Não consegui conectar ao Ollama local.\n\n"
            "Verifique se o Ollama está rodando e se o endpoint está correto.\n"
            "Exemplo: `ollama serve` e depois tente novamente."
        ), "erro_conexao"
    except requests.exceptions.Timeout:
        return "A geração demorou além do tempo limite. Tente uma pergunta mais curta.", "erro_timeout"
    except Exception as e:
        return f"Ocorreu um erro ao consultar o modelo local: {e}", "erro_geral"

# =========================
# APP STREAMLIT
# =========================
perfil, transacoes, historico, produtos = carregar_dados()
receita, despesa, saldo, taxa_poupanca, top_cat = calcular_kpis(transacoes)

st.title("💼 FINA+ — Saúde Financeira + Suitability Educativo")
st.caption("Assistente educativo para organização financeira e aderência ao perfil de risco.")

st.warning("⚠️ Este agente oferece orientação educativa e não promete rentabilidade. Não substitui consultoria financeira regulada.")

# Sidebar
with st.sidebar:
    st.subheader("📌 Cliente (simulado)")
    st.write(f"**Nome:** {perfil.get('nome', 'N/A')}")
    st.write(f"**Perfil:** {perfil.get('perfil_investidor', 'N/A')}")
    st.write(f"**Objetivo:** {perfil.get('objetivo_principal', 'N/A')}")
    st.markdown(f"<span class='badge'>Modelo: {MODELO}</span>", unsafe_allow_html=True)
    st.write("")
    st.caption(f"Endpoint Ollama: {OLLAMA_URL}")

    st.divider()
    st.subheader("🧭 Ações rápidas")
    if st.button("🧹 Limpar conversa", use_container_width=True):
        st.session_state.messages = [{
            "role": "assistant",
            "content": "Conversa reiniciada. Como posso te ajudar com suas finanças hoje?"
        }]
        st.rerun()

# KPIs
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown("<div class='kpi-card'><div class='kpi-title'>Receita estimada</div>"
                f"<div class='kpi-value'>{brl(receita)}</div></div>", unsafe_allow_html=True)
with k2:
    st.markdown("<div class='kpi-card'><div class='kpi-title'>Despesa estimada</div>"
                f"<div class='kpi-value'>{brl(despesa)}</div></div>", unsafe_allow_html=True)
with k3:
    st.markdown("<div class='kpi-card'><div class='kpi-title'>Saldo estimado</div>"
                f"<div class='kpi-value'>{brl(saldo)}</div></div>", unsafe_allow_html=True)
with k4:
    st.markdown("<div class='kpi-card'><div class='kpi-title'>Taxa de poupança</div>"
                f"<div class='kpi-value'>{taxa_poupanca:.1f}%</div></div>", unsafe_allow_html=True)

# Insights visuais
colA, colB = st.columns([1.2, 1])

with colA:
    st.markdown("<div class='section-title'>📊 Categorias de gasto (top 8)</div>", unsafe_allow_html=True)
    if len(top_cat) > 0:
        chart_df = top_cat.reset_index()
        chart_df.columns = ["Categoria", "Valor"]
        st.bar_chart(chart_df.set_index("Categoria"))
    else:
        st.info("Sem dados de categoria para exibir.")

with colB:
    st.markdown("<div class='section-title'>🧾 Resumo por categoria</div>", unsafe_allow_html=True)
    if len(top_cat) > 0:
        tab = pd.DataFrame({"Categoria": top_cat.index, "Valor": [brl(v) for v in top_cat.values]})
        st.dataframe(tab, use_container_width=True, hide_index=True)
    else:
        st.info("Sem dados para tabela.")

with st.expander("📌 Fontes de contexto usadas neste agente"):
    st.markdown(
        "- `perfil_investidor.json`\n"
        "- `transacoes.csv`\n"
        "- `historico_atendimento.csv`\n"
        "- `produtos_financeiros.json`\n"
        "- O agente usa amostras recentes + resumo consolidado para reduzir alucinação."
    )

# Botões de prompt inicial
st.markdown("### Sugestões rápidas")
b1, b2, b3 = st.columns(3)
if b1.button("Como melhorar meu orçamento este mês?", use_container_width=True):
    st.session_state.quick_prompt = "Como melhorar meu orçamento este mês?"
if b2.button("Sou moderado, quais opções fazem sentido?", use_container_width=True):
    st.session_state.quick_prompt = "Sou moderado, quais opções fazem sentido?"
if b3.button("Quais categorias mais pesam nos meus gastos?", use_container_width=True):
    st.session_state.quick_prompt = "Quais categorias mais pesam nos meus gastos?"

# Histórico de chat
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Olá! Eu sou o FINA+. Posso te ajudar com gastos, orçamento, perfil de risco e comparação educativa de produtos financeiros."
        }
    ]

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["content"])

# Entrada (chat_input ou botão rápido)
pergunta = st.chat_input("Digite sua dúvida financeira...")
if not pergunta and st.session_state.get("quick_prompt"):
    pergunta = st.session_state.pop("quick_prompt")

if pergunta:
    st.session_state.messages.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.write(pergunta)

    intencao = detectar_intencao(pergunta)
    contexto = montar_contexto(perfil, transacoes, historico, produtos, intencao)

    with st.chat_message("assistant"):
        with st.spinner("Analisando seus dados e montando resposta..."):
            resposta, status = perguntar_ollama(pergunta, contexto)
            st.write(resposta)
            st.caption(f"Intenção detectada: `{intencao}` | Status: `{status}`")

    st.session_state.messages.append({"role": "assistant", "content": resposta})

    save_log({
        "timestamp_utc": datetime.utcnow().isoformat(),
        "pergunta": pergunta,
        "intencao": intencao,
        "status": status,
        "resposta": resposta
    })
