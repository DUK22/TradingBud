"""Modelos de dados (SQLAlchemy / SQLite).

Esquema enxuto e auditável:

    User 1---N BrokerageNote 1---N Trade
    User 1---1 B3Connection   (stub p/ integração futura)

Posições em aberto e apuração mensal são CALCULADAS sob demanda pelo
tax_engine a partir das Trades — assim nunca há dado derivado desatualizado.
Valores monetários usam Numeric(18,6) e são manipulados como Decimal.
"""
from datetime import UTC, datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy.ext.mutable import MutableList
from werkzeug.security import check_password_hash, generate_password_hash

from .crypto import EncryptedString
from .extensions import db

NUM = db.Numeric(18, 6)


def utcnow() -> datetime:
    """Timestamp UTC timezone-aware (substitui o depreciado datetime.utcnow)."""
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    cpf = db.Column(EncryptedString())  # criptografado em repouso (LGPD)
    layout_mercado = db.Column(db.Text)  # JSON do layout da página Mercado
    strategy = db.Column(db.Text)        # legado: estratégia única (migrada p/ StrategyProfile)
    active_strategy_id = db.Column(db.Integer)  # id da StrategyProfile selecionada
    created_at = db.Column(db.DateTime, default=utcnow)

    notes = db.relationship(
        "BrokerageNote", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    trades = db.relationship(
        "Trade", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    b3 = db.relationship(
        "B3Connection", backref="user", uselist=False, cascade="all, delete-orphan"
    )
    journal = db.relationship(
        "Note", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    strategies = db.relationship(
        "StrategyProfile", backref="user", lazy=True, cascade="all, delete-orphan",
        foreign_keys="StrategyProfile.user_id",
    )

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def __repr__(self):
        return f"<User {self.email}>"


class BrokerageNote(db.Model):
    """Nota de corretagem (padrão SINACOR). Guarda os totais financeiros
    extraídos do PDF e o texto bruto (para auditoria/recalibração do parser)."""

    __tablename__ = "brokerage_notes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    broker = db.Column(db.String(60), default="BTG")
    note_number = db.Column(db.String(40))
    trade_date = db.Column(db.Date, nullable=False, index=True)     # data do pregão
    settlement_date = db.Column(db.Date)                            # data de liquidação
    source = db.Column(db.String(20), default="OCR")               # OCR | B3 | MANUAL

    # Custos (compõem o custo de aquisição / reduzem a venda)
    corretagem = db.Column(NUM, default=0)
    emolumentos = db.Column(NUM, default=0)       # emolumentos B3/Bovespa
    taxa_liquidacao = db.Column(NUM, default=0)   # CBLC
    taxa_registro = db.Column(NUM, default=0)     # CBLC
    iss = db.Column(NUM, default=0)
    outras = db.Column(NUM, default=0)            # ANA, custódia, etc.

    # Segmento e resultado pré-apurado (notas BM&F / futuros: WIN, WDO, IND...)
    segment = db.Column(db.String(20), default="BOVESPA")   # BOVESPA | BMF
    daytrade_gross = db.Column(NUM, default=0)    # ajuste day trade (BM&F)
    normal_gross = db.Column(NUM, default=0)      # ajuste posição/normal (BM&F)

    # Tributos retidos na fonte (crédito a compensar)
    irrf_day = db.Column(NUM, default=0)          # 1% s/ lucro day trade
    irrf_swing = db.Column(NUM, default=0)        # 0,005% "dedo-duro" s/ vendas

    net_value = db.Column(NUM, default=0)         # líquido a receber/pagar
    provisional = db.Column(db.Boolean, default=False, nullable=False)  # estimativa do dia
    filename = db.Column(db.String(255))
    raw_text = db.Column(db.Text)                 # texto extraído (auditoria)
    created_at = db.Column(db.DateTime, default=utcnow)

    trades = db.relationship(
        "Trade", backref="note", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def total_costs(self) -> Decimal:
        vals = [self.corretagem, self.emolumentos, self.taxa_liquidacao,
                self.taxa_registro, self.iss, self.outras]
        return sum((Decimal(str(v or 0)) for v in vals), Decimal("0"))


class Trade(db.Model):
    """Um negócio (linha de 'Negócios realizados' da nota)."""

    __tablename__ = "trades"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    note_id = db.Column(db.Integer, db.ForeignKey("brokerage_notes.id"), index=True)

    trade_date = db.Column(db.Date, nullable=False, index=True)
    asset = db.Column(db.String(20), nullable=False, index=True)   # ticker (ex.: PETR4)
    market = db.Column(db.String(20), default="VISTA")             # VISTA|FRACIONARIO|OPCAO|TERMO
    side = db.Column(db.String(1), nullable=False)                 # 'C' compra | 'V' venda
    quantity = db.Column(NUM, nullable=False)
    price = db.Column(NUM, nullable=False)
    gross_value = db.Column(NUM, nullable=False)                   # quantidade * preço
    created_at = db.Column(db.DateTime, default=utcnow)

    def __repr__(self):
        return f"<Trade {self.side} {self.quantity} {self.asset} @ {self.price}>"


class B3Connection(db.Model):
    """Stub de conexão com a Área do Investidor da B3.
    Persiste tokens/estado quando a integração for ativada."""

    __tablename__ = "b3_connections"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    status = db.Column(db.String(20), default="disconnected")  # disconnected|connected|error
    access_token = db.Column(db.Text)
    refresh_token = db.Column(db.Text)
    token_expires_at = db.Column(db.DateTime)
    last_sync_at = db.Column(db.DateTime)
    last_message = db.Column(db.String(255))


class Note(db.Model):
    """Entrada do diário de trades (texto rico já sanitizado)."""

    __tablename__ = "notes_journal"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), default="")
    body = db.Column(db.Text, default="")            # HTML sanitizado (Quill)
    tags = db.Column(db.String(255), default="")     # separadas por vírgula
    asset = db.Column(db.String(20), index=True)     # ticker vinculado (opcional)
    analysis_history = db.Column(MutableList.as_mutable(db.JSON), default=list, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


class StrategyProfile(db.Model):
    """Estratégia nomeada do trader (selecionável; usada como contexto da IA)."""

    __tablename__ = "strategy_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default="Estratégia")
    content = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
