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
   acumulados** em buckets separados (day / swing / FII), **isenção de
   R$ 20.000/mês** só para vendas à vista de ações no swing, alíquotas por
   classe de ativo (**15% swing**, **20% day trade**, **20% FII**; ETF/BDR sem
   isenção), IRRF compensado por modalidade (1% day x 0,005% "dedo-duro"),
   regra do **DARF mínimo de R$10** (acumula p/ o mês seguinte) e **DARF**
   (código 6015). Avisos automáticos: venda a descoberto e ETF de renda fixa.
   **Eventos corporativos** (desdobramento/grupamento/bonificação) são
   lançados na tela "Ajustes" e aplicados na data correta.
4. **Integração B3 (Área do Investidor)** — arquitetura pronta (`B3InvestidorClient`)
   com pontos de extensão `authenticate()` / `get_movements()` e o mapeamento
   `to_trades()` já implementado. Basta ativar quando as credenciais OAuth2
   estiverem disponíveis.
5. **Multi-usuário (SaaS)** — cadastro/login, senhas com hash, dados isolados
   por usuário, **verificação de e-mail** e **reset de senha** por token
   (e-mails via SMTP configurável; sem SMTP, o link sai no log — modo dev).
6. **Cotações** — brapi.dev (com `BRAPI_TOKEN`) com fallback Yahoo Finance.
7. **Automação** — upload de notas **em lote** com deduplicação por número,
   drill-down da apuração (mês → operação por operação) e lembrete mensal de
   DARF por e-mail (`flask darf-remind`, agendável via cron).
8. **Relatório anual DIRPF** — bens e direitos em 31/12 com discriminação
   pronta (copiar/colar), renda variável mês a mês, isentos e prejuízos a
   transportar; em página e PDF (`/relatorio`).
9. **Reconciliação** — confere a planilha de Negociação da B3 contra as notas
   importadas e aponta o que falta ou diverge, sem importar nada.

## Stack

- **Backend:** Flask + Flask-Login + Flask-WTF (CSRF)
- **ORM/DB:** SQLAlchemy + **SQLite** (portabilidade inicial)
- **OCR:** pdfplumber
- **Front:** Jinja2 + **Tailwind CSS** (CDN) + Chart.js
- **Cálculo:** `Decimal` em todo o motor fiscal (sem floats)

## Estrutura

```
ir-traders/
├── run.py                  # ponto de entrada (dev)
├── wsgi.py                 # entrypoint WSGI (gunicorn/waitress)
├── config.py               # config por env vars (SECRET_KEY, CPF_ENC_KEY...)
├── seed.py                 # popula dados de demonstração
├── requirements*.txt       # runtime / -dev (testes+lint) / -prod (WSGI)
├── Dockerfile              # build multi-stage (CSS + gunicorn)
├── docker-entrypoint.sh    # aplica migrações e sobe o servidor
├── package.json            # build do Tailwind (gera app/static/app.css)
├── tailwind.config.js
├── migrations/             # Alembic (Flask-Migrate)
├── app/
│   ├── __init__.py         # application factory (extensões, CSP, logging)
│   ├── extensions.py       # db, migrate, login, csrf, limiter
│   ├── crypto.py           # EncryptedString (CPF criptografado — LGPD)
│   ├── models.py           # User, BrokerageNote, Trade, B3Connection
│   ├── auth.py             # cadastro/login/logout (rate-limited)
│   ├── main.py             # dashboard, upload, notas, apuração, conta/LGPD, B3
│   ├── utils.py            # filtros pt-BR (R$, %, meses)
│   ├── services/
│   │   ├── ocr.py          # parser SINACOR/BTG (BOVESPA e BM&F)
│   │   ├── tax_engine.py   # preço médio, day/swing, apuração, impostos
│   │   └── b3_client.py    # stub de integração B3 (Área do Investidor)
│   ├── static/             # app.css (build do Tailwind) + src/input.css
│   └── templates/          # UI Tailwind
└── tests/                  # pytest: motor fiscal, OCR, auth, utils, b3, rotas
```

## Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env    # ajuste SECRET_KEY etc. (opcional em dev)
python seed.py          # opcional: cria dados de demonstração
python run.py           # http://127.0.0.1:5000
```

**Login de demonstração:** `demo@trader.com` / `demo1234`

### Configuração / segurança

Variáveis de ambiente (veja `.env.example`):

| Variável | Padrão | Observação |
|----------|--------|------------|
| `SECRET_KEY` | gerada em dev | **obrigatória** quando `FLASK_ENV=production` |
| `CPF_ENC_KEY` | fallback dev | chave Fernet; **obrigatória** em produção (CPF criptografado) |
| `FLASK_ENV` | `development` | em `production` liga cookies `Secure`/HSTS/ProxyFix |
| `FLASK_DEBUG` | `0` | `1` só em dev (o debugger expõe console RCE) |
| `DATABASE_URL` | SQLite local | ex.: `postgresql://...` (Postgres em produção) |
| `RATELIMIT_STORAGE_URI` | `memory://` | use Redis em produção (múltiplos workers) |

Já incluído: **CSRF** em todas as rotas POST, **rate limiting** no login/cadastro,
cabeçalhos de segurança (**CSP, HSTS, X-Frame-Options, X-Content-Type-Options**),
cookies `HttpOnly`/`SameSite`. **LGPD:** CPF criptografado em repouso (Fernet) e,
em *Minha conta*, exportação (JSON) e exclusão da conta com remoção em cascata.

### Banco de dados e migrações (Alembic)

Schema versionado com **Flask-Migrate**. Em dev as migrações são aplicadas no
startup. Após alterar os modelos:

```bash
export FLASK_APP=run.py
flask db migrate -m "descrição"   # gera a migração
flask db upgrade                  # aplica
```

Em produção, aplique no deploy (`flask db upgrade`) e use `SKIP_SCHEMA_INIT=1`
(evita corrida entre workers).

### Front-end (Tailwind)

O CSS é **gerado localmente** (sem CDN). Para regenerar após mexer nos templates
(precisa de Node): `npm install && npm run build:css`. O `app/static/app.css` já
vem versionado, então a app roda sem Node; no Docker o CSS é recompilado no build.

## Produção (WSGI / Docker)

Não use o servidor de desenvolvimento em produção. Use um WSGI:

```bash
pip install -r requirements.txt -r requirements-prod.txt
gunicorn -b 0.0.0.0:8000 -w 3 wsgi:app          # Linux
waitress-serve --listen=0.0.0.0:8000 wsgi:app   # Windows
```

**Docker** (multi-stage: compila o CSS e roda gunicorn):

```bash
docker build -t ir-traders .
docker run -p 8000:8000 \
  -e SECRET_KEY="..." -e CPF_ENC_KEY="..." ir-traders
```

### Deploy no Render (acesso pelo celular, sempre no ar)

1. Suba o projeto no **GitHub** (veja "Salvar na nuvem" abaixo).
2. Gere uma chave Fernet para o CPF:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. No [Render](https://render.com): **New → Blueprint**, aponte para o repositório
   (ele lê o `render.yaml`) e crie. Isso provisiona a web app (Docker) **e** um
   PostgreSQL grátis, já conectados.
4. No serviço criado, defina a variável **`CPF_ENC_KEY`** com a chave do passo 2
   (o `SECRET_KEY` o Render gera sozinho).
5. O deploy aplica as migrações e sobe o gunicorn; você recebe uma URL `https://…`
   acessível de qualquer celular. (Planos free hibernam e o Postgres expira em
   ~90 dias — para uso sério, suba de plano.)

> **Por que não Vercel?** A Vercel é feita para apps serverless/estáticos; um Flask
> com banco não encaixa bem lá. Render/Railway/Fly.io rodam nosso Docker direto.

### Salvar na nuvem (GitHub)

As mudanças já são salvas em **git** localmente (`git add -A && git commit -m "..."`).
Para backup online e histórico: crie um repositório no GitHub e
`git remote add origin <url>` + `git push -u origin main`.

## Testes e lint

```bash
pip install -r requirements-dev.txt
pytest            # 34 testes
ruff check .      # lint
```

Cobertura: motor fiscal, parser OCR (BOVESPA e BM&F), autenticação e
**isolamento entre usuários**, filtros, mapeamento B3, paginação, criptografia
de CPF, exportação/exclusão de conta e geração da DARF em PDF. CI roda `ruff` +
`pytest` a cada push/PR (`.github/workflows/ci.yml`).

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

- Relatório anual consolidado para a DIRPF.
- Ativar OAuth2 da B3 e sincronização automática (cliente já preparado).
- OCR de notas escaneadas (imagem) via Tesseract.
- Regras específicas para opções (exercício) e aluguel de ações (BTC).

Já entregue: DARF em PDF, dashboard com métricas (win rate, melhor/pior),
sparklines e barra de isenção de R$20k.

## Acesso rápido

- **Quero usar (1 clique):** `start.bat` (Windows) ou `start.sh`
  (macOS/Linux) — cria o ambiente, instala tudo, popula o demo e sobe o servidor.
- **Manual:** `pip install -r requirements.txt && python seed.py && python run.py`
  e acesse http://127.0.0.1:5000 (login `demo@trader.com` / `demo1234`).

> É uma aplicação web servida por Python (Flask) — não existe um `index.html`
> para abrir direto; a home é a rota `/` (dashboard) enquanto o servidor roda.

