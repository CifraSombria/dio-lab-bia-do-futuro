# Base de Conhecimento

## Dados Utilizados

Descreva se usou os arquivos da pasta `data`, por exemplo:

| Arquivo | Formato | Utilização no Agente |
|---------|---------|---------------------|
| `historico_atendimento.csv` | CSV | Identificar dúvidas recorrentes e melhorar continuidade do atendimento |
| `perfil_investidor.json` | JSON | Personalizar orientações de suitability conforme perfil de risco |
| `produtos_financeiros.json` | JSON | Comparar produtos por risco, liquidez, objetivo e horizonte |
| `transacoes.csv` | CSV | Analisar padrão de gastos, sazonalidade e sinais de saúde financeira |

> [!TIP]
> **Quer um dataset mais robusto?** Você pode utilizar datasets públicos do [Hugging Face](https://huggingface.co/datasets) relacionados a finanças, desde que sejam adequados ao contexto do desafio.

---

## Adaptações nos Dados

> Você modificou ou expandiu os dados mockados? Descreva aqui.

Até o momento, **não foram realizadas modificações estruturais** nos dados mockados originais da pasta `data/`.

---

## Estratégia de Integração

### Como os dados são carregados?
> Descreva como seu agente acessa a base de conhecimento.

Os arquivos CSV/JSON são carregados no início da sessão (startup do app) e mantidos em memória para consulta rápida.  
A cada pergunta do usuário, o agente:
1. classifica a intenção;
2. consulta apenas os blocos relevantes da base;
3. monta um contexto compacto para envio ao modelo.

Esse fluxo evita prompts excessivamente longos e melhora a precisão por tema.

### Como os dados são usados no prompt?
> Os dados vão no system prompt? São consultados dinamicamente?

Os dados **não** são colocados integralmente no `system prompt`.  
A estratégia adotada é:

- `system prompt`: regras fixas (persona, limites, segurança, anti-alucinação);
- contexto dinâmico: trechos relevantes dos dados (perfil, transações recentes, produtos compatíveis e histórico relacionado), injetados no prompt do usuário conforme a intenção detectada.

Assim, o agente responde com base em evidências da base e mantém consistência de comportamento.

---

## Exemplo de Contexto Montado

> Mostre um exemplo de como os dados são formatados para o agente.

```text
Contexto do Cliente (extraído da base):

Perfil do Investidor:
- Nome: João Silva
- Perfil: Moderado
- Objetivo principal: Reserva + crescimento gradual
- Horizonte: Médio prazo

Resumo Financeiro (últimos 30 dias):
- Receita total: R$ 7.500
- Despesa total: R$ 6.200
- Taxa de poupança estimada: 17,3%
- Categorias mais relevantes: Alimentação (22%), Transporte (15%), Lazer (13%)

Produtos Compatíveis (base interna):
1) CDB Liquidez Diária
   - Risco: Baixo
   - Liquidez: Alta
   - Indicação: Reserva de emergência
2) Fundo Multimercado Conservador
   - Risco: Médio-baixo
   - Liquidez: D+X
   - Indicação: Perfil moderado com horizonte médio

Histórico de Atendimento Relacionado:
- Tema recorrente: controle de gastos no cartão
- Dúvida anterior: diferença entre liquidez e vencimento

Instrução de Resposta:
- Explicar em linguagem simples
- Não prometer rentabilidade
- Sugerir próximo passo prático
