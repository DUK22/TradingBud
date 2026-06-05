# IR Traders — Gestão de Imposto de Renda para Traders (Renda Variável)

Aplicação web (Flask) para organizar e apurar o Imposto de Renda de operações
em renda variável: importa notas de corretagem (PDF/SINACOR), calcula preço
médio, separa **Day Trade** de **Swing Trade**, apura mês a mês com compensação
de prejuízos e alíquotas corretas, e mostra tudo num dashboard.

> ⚠️ **Aviso:** ferramenta de apoio à organização fiscal. **Não constitui
> aconselhamento contábil ou tributário.** Confira os cálculos com seu contador.

---

## Funcionalidades

1. **OCR de Nota de Corretagem** — upload de PDF (padrão SINACOR / BTG). Extrai
   ativo, quantidade, preço, taxas (corretagem, emolumentos, taxa de liquidação/
   registro, ISS) e IRRF. Usa **pdfplumber**. O texto bruto fica salvo na nota
   para auditoria e calibração do parser.
2. **Preço Médio Ponderado** — custo de aquisição incorpora as taxas; venda é
   líquida das taxas. Day Trade x Swing são **separados automaticamente** por
   `(ativo, dia)`.
3. **Apuração Mensal** — lucro/prejuízo por mês, **compensação de prejuízos
   acumulados** (modalidades separadas: prejuízo de day só compensa day, swing
   só compensa swing), **isenção de R$ 20.000/mês** para vendas à vista de ações
   no swing, alíquotas **15% (swing)** e **20% (day trade)**, dedução do IRRF
   retido e **DARF** (código 6015).
4. **Integração B3 (Área do Investidor)** — arquitetura pronta (`B3InvestidorClient`)
   com pontos de extensão `authenticate()` / `get_movements()` e o mapeamento
   `to_trades()` já implementado. Basta ativar quando as credenciais OAuth2
   estiverem disponíveis.
5. **Multi-usuário (SaaS)** — cadastro/login, senhas com hash, dados isolados por
   usuário.

## Stack

- **Backend:** Flask + Flask-Login + Flask-WTF (CSRF)
- **ORM/DB:** SQLAlchemy + **SQLite** (portabilidade inicial)
- **OCR:** pdfplumber
- **Front:** Jinja2 + **Tailwind CSS** (CDN) + Chart.js
- **Cálculo:** `Decimal` em todo o motor fiscal (sem floats)

## Estrutura

```
ir-traders/
├── run.py                  # ponto de entrada
├── config.py               # config (env vars; SQLite por padrão)
├── seed.py                 # popula dados de demonstração
├── requirements.txt
├── app/
│   ├── __init__.py         # application factory
│   ├── extensions.py       # db, login_manager
│   ├── models.py           # User, BrokerageNote, Trade, B3Connection
│   ├── auth.py             # cadastro/login/logout
│   ├── main.py             # dashboard, upload, notas, apuração, posições, B3
│   ├── utils.py            # filtros pt-BR (R$, %, meses)
│   ├── services/
│   │   ├── ocr.py          # parser SINACOR/BTG (plugável por corretora)
│   │   ├── tax_engine.py   # preço médio, day/swing, apuração, impostos
│   │   └── b3_client.py    # stub de integração B3 (Área do Investidor)
│   └── templates/          # UI Tailwind
└── tests/
    └── test_tax_engine.py  # 7 testes do motor fiscal
```

## Como rodar

```bash
pip install -r requirements.txt
python seed.py          # opcional: cria dados de demonstração
python run.py           # http://127.0.0.1:5000
```

**Login de demonstração:** `demo@trader.com` / `demo1234`

## Testes

```bash
python tests/test_tax_engine.py     # ou: pytest -q
```

Cobrem: preço médio ponderado, detecção de day trade, isenção de R$20k,
alíquotas 15%/20%, compensação de prejuízo e separação das modalidades.

## Regras fiscais e simplificações (MVP)

- **Day Trade** = quantidade comprada **e** vendida do mesmo ativo no mesmo dia.
- **Isenção:** aplicada quando as vendas à vista de **ações** no swing somam
  ≤ R$ 20.000 no mês (lucro isento; prejuízo isento não é compensável). Opções,
  ETFs e demais mercados não entram na isenção.
- **DARF** abaixo de R$ 10,00 é sinalizado para acúmulo (não recolhido isolado).
- IRRF (1% day / 0,005% swing) é deduzido do imposto devido.
- Simplificações conscientes: rateio de custos por volume financeiro; isenção
  aplicada no agregado mensal das ações à vista. Pontos sinalizados no código.

## Calibração do parser (BTG)

O layout textual das notas varia por corretora/versão. O parser já reconhece o
padrão SINACOR/BTG; para precisão no seu layout exato, basta uma **nota real da
BTG** — ajustamos as expressões com base no texto extraído (salvo em
`BrokerageNote.raw_text`).

## Roadmap

- Ativar OAuth2 da B3 e sincronização automática (cliente já preparado).
- Geração de DARF (PDF) e relatório anual para a DIRPF.
- OCR de notas escaneadas (imagem) via Tesseract.
- Suporte a FIIs, ETFs, opções e mercado futuro com regras específicas.

## Acesso rápido

- **Só quero ver a cara:** abra `preview/index.html` no navegador (snapshot
  estático com os dados de demonstração; não envia formulários).
- **Quero usar de verdade (1 clique):** `start.bat` (Windows) ou `start.sh`
  (macOS/Linux) — cria o ambiente, instala tudo, popula o demo e sobe o servidor.
- **Manual:** `pip install -r requirements.txt && python seed.py && python run.py`
  e acesse http://127.0.0.1:5000 (login `demo@trader.com` / `demo1234`).

> É uma aplicação web servida por Python (Flask) — não existe um `index.html`
> para abrir direto; a home é a rota `/` (dashboard) enquanto o servidor roda.
