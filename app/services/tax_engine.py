"""Engine de cálculo de IR para renda variável (pessoa física).

Responsabilidades:
  1. Alocar os custos da nota (corretagem, emolumentos, ISS...) a cada negócio,
     proporcionalmente ao volume financeiro.
  2. Separar automaticamente DAY TRADE de SWING TRADE por (ativo, dia):
     day trade = quantidade que foi comprada E vendida do mesmo ativo no mesmo dia.
  3. Calcular o PREÇO MÉDIO PONDERADO das posições de swing (custo de aquisição
     inclui as taxas; a venda é líquida das taxas).
  4. Apurar mês a mês: resultado, isenção de R$20k (ações à vista no swing),
     compensação de prejuízos acumulados (buckets separados Day x Swing),
     alíquotas (15% swing / 20% day), IRRF retido e DARF (código 6015).

IMPORTANTE: implementação para fins de organização/estimativa. Não substitui
a conferência de um contador. Regras simplificadas estão sinalizadas no código.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

D0 = Decimal("0")
CENT = Decimal("0.01")

# --- Parâmetros fiscais (renda variável PF) ---
ALIQ_SWING = Decimal("0.15")          # 15% sobre o ganho líquido em swing trade
ALIQ_DAY = Decimal("0.20")            # 20% sobre o ganho líquido em day trade
ISENCAO_SWING_MENSAL = Decimal("20000")   # isenção p/ vendas à vista de ações no swing
DARF_MINIMO = Decimal("10")           # DARF abaixo disso é acumulado p/ meses seguintes
DARF_CODIGO = "6015"                  # ganhos líquidos em renda variável - PF

# Mercados elegíveis à isenção mensal de R$20k (ações à vista)
EQUITY_MARKETS = {"VISTA", "FRACIONARIO"}


def _d(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return D0
    return Decimal(str(x))


def money(x) -> Decimal:
    return _d(x).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Estruturas intermediárias
# --------------------------------------------------------------------------- #
@dataclass
class Leg:
    asset: str
    trade_date: date
    side: str            # 'C' | 'V'
    qty: Decimal
    price: Decimal
    gross: Decimal
    costs: Decimal       # custos alocados (corretagem+emol+iss+...)
    market: str = "VISTA"


@dataclass
class DayTradeResult:
    asset: str
    trade_date: date
    qty: Decimal
    avg_buy: Decimal
    avg_sell: Decimal
    gross_result: Decimal   # qty*(avg_sell-avg_buy)
    costs: Decimal
    net_result: Decimal     # gross_result - costs
    market: str = "VISTA"


@dataclass
class SwingSale:
    asset: str
    trade_date: date
    qty: Decimal
    sell_price: Decimal
    avg_price: Decimal      # preço médio na hora da venda
    proceeds: Decimal       # qty*price - custos da venda
    gross: Decimal          # qty*price (bruto, p/ teste da isenção)
    result: Decimal         # proceeds - (avg*qty)
    market: str = "VISTA"


@dataclass
class Position:
    asset: str
    qty: Decimal
    avg_price: Decimal
    total_cost: Decimal
    market: str = "VISTA"

    @property
    def market_cost(self) -> Decimal:
        return self.qty * self.avg_price


@dataclass
class MonthlyApuracao:
    year: int
    month: int
    # resultados brutos do mês
    day_result: Decimal = D0
    swing_result: Decimal = D0           # soma de todos os swing sales (antes de isenção)
    equity_swing_gross: Decimal = D0     # vendas à vista de ações (teste dos 20k)
    exempt_result: Decimal = D0          # parcela isenta (ações à vista <= 20k)
    # bases tributáveis após isenção e compensação
    swing_taxable_base: Decimal = D0
    day_taxable_base: Decimal = D0
    swing_loss_used: Decimal = D0
    day_loss_used: Decimal = D0
    swing_loss_acc: Decimal = D0         # prejuízo acumulado APÓS o mês
    day_loss_acc: Decimal = D0
    # impostos
    swing_tax: Decimal = D0
    day_tax: Decimal = D0
    irrf_day: Decimal = D0
    irrf_swing: Decimal = D0
    darf: Decimal = D0                   # imposto a pagar (líquido de IRRF)
    darf_below_min: bool = False

    @property
    def total_result(self) -> Decimal:
        return self.day_result + self.swing_result

    @property
    def total_tax(self) -> Decimal:
        return self.swing_tax + self.day_tax


@dataclass
class ApuracaoResult:
    months: list = field(default_factory=list)        # list[MonthlyApuracao]
    positions: list = field(default_factory=list)     # list[Position]
    day_results: list = field(default_factory=list)
    swing_sales: list = field(default_factory=list)
    final_day_loss: Decimal = D0
    final_swing_loss: Decimal = D0

    # agregados de conveniência (ano corrente preenchido pela rota)
    def month(self, year, month):
        for m in self.months:
            if m.year == year and m.month == month:
                return m
        return None


# --------------------------------------------------------------------------- #
# 1. Custos -> legs
# --------------------------------------------------------------------------- #
def build_legs(notes) -> list:
    """Transforma notas+trades em 'legs' com custos rateados por volume."""
    legs = []
    for note in notes:
        trades = list(note.trades)
        total_gross = sum((_d(t.gross_value) for t in trades), D0)
        note_costs = _d(note.total_costs)
        for t in trades:
            gross = _d(t.gross_value)
            share = (gross / total_gross) if total_gross > 0 else D0
            legs.append(Leg(
                asset=t.asset,
                trade_date=note.trade_date,
                side=t.side,
                qty=_d(t.quantity),
                price=_d(t.price),
                gross=gross,
                costs=note_costs * share,
                market=t.market or "VISTA",
            ))
    return legs


# --------------------------------------------------------------------------- #
# 2. Separa Day Trade de Swing por (ativo, dia)
# --------------------------------------------------------------------------- #
def split_day_swing(legs) -> tuple:
    groups = defaultdict(list)
    for leg in legs:
        groups[(leg.asset, leg.trade_date)].append(leg)

    day_results, swing_legs = [], []

    for (asset, d), group in groups.items():
        buys = [l for l in group if l.side == "C"]
        sells = [l for l in group if l.side == "V"]
        buy_qty = sum((l.qty for l in buys), D0)
        sell_qty = sum((l.qty for l in sells), D0)
        dt_qty = min(buy_qty, sell_qty)
        group_costs = sum((l.costs for l in group), D0)
        market = group[0].market

        if dt_qty <= 0:
            swing_legs.extend(group)
            continue

        buy_val = sum((l.qty * l.price for l in buys), D0)
        sell_val = sum((l.qty * l.price for l in sells), D0)
        avg_buy = buy_val / buy_qty
        avg_sell = sell_val / sell_qty

        traded_qty = buy_qty + sell_qty
        day_costs = group_costs * (2 * dt_qty) / traded_qty if traded_qty > 0 else D0
        gross_result = dt_qty * (avg_sell - avg_buy)
        day_results.append(DayTradeResult(
            asset=asset, trade_date=d, qty=dt_qty,
            avg_buy=avg_buy, avg_sell=avg_sell,
            gross_result=gross_result, costs=day_costs,
            net_result=gross_result - day_costs, market=market,
        ))

        # Sobras viram swing (com custos residuais rateados por quantidade)
        rem_buy = buy_qty - dt_qty
        rem_sell = sell_qty - dt_qty
        rem_costs = group_costs - day_costs
        rem_qty = rem_buy + rem_sell
        if rem_buy > 0:
            swing_legs.append(Leg(
                asset=asset, trade_date=d, side="C", qty=rem_buy, price=avg_buy,
                gross=rem_buy * avg_buy,
                costs=(rem_costs * rem_buy / rem_qty) if rem_qty > 0 else D0,
                market=market,
            ))
        if rem_sell > 0:
            swing_legs.append(Leg(
                asset=asset, trade_date=d, side="V", qty=rem_sell, price=avg_sell,
                gross=rem_sell * avg_sell,
                costs=(rem_costs * rem_sell / rem_qty) if rem_qty > 0 else D0,
                market=market,
            ))

    return day_results, swing_legs


# --------------------------------------------------------------------------- #
# 3. Preço médio ponderado (posições de swing)
# --------------------------------------------------------------------------- #
def run_positions(swing_legs) -> tuple:
    positions: dict = {}
    swing_sales = []

    for leg in sorted(swing_legs, key=lambda l: (l.trade_date, 0 if l.side == "C" else 1)):
        pos = positions.get(leg.asset)
        if pos is None:
            pos = Position(asset=leg.asset, qty=D0, avg_price=D0, total_cost=D0, market=leg.market)
            positions[leg.asset] = pos

        if leg.side == "C":
            # Custo de aquisição inclui as taxas
            pos.total_cost += leg.qty * leg.price + leg.costs
            pos.qty += leg.qty
            pos.avg_price = (pos.total_cost / pos.qty) if pos.qty > 0 else D0
        else:  # venda
            avg = pos.avg_price
            cost_basis = avg * leg.qty
            proceeds = leg.qty * leg.price - leg.costs   # venda líquida de taxas
            swing_sales.append(SwingSale(
                asset=leg.asset, trade_date=leg.trade_date, qty=leg.qty,
                sell_price=leg.price, avg_price=avg, proceeds=proceeds,
                gross=leg.qty * leg.price, result=proceeds - cost_basis,
                market=leg.market,
            ))
            pos.qty -= leg.qty
            pos.total_cost -= cost_basis
            if pos.qty <= Decimal("0.000001"):
                pos.qty = D0
                pos.total_cost = D0
                pos.avg_price = D0

    open_positions = [p for p in positions.values() if p.qty > 0]
    return open_positions, swing_sales


# --------------------------------------------------------------------------- #
# 4. Apuração mensal com compensação de prejuízo e impostos
# --------------------------------------------------------------------------- #
def monthly_apuracao(day_results, swing_sales, notes) -> list:
    keys = set()
    for r in day_results:
        keys.add((r.trade_date.year, r.trade_date.month))
    for s in swing_sales:
        keys.add((s.trade_date.year, s.trade_date.month))
    for n in notes:
        keys.add((n.trade_date.year, n.trade_date.month))

    months = []
    swing_loss_acc = D0   # prejuízo compensável acumulado (>= 0)
    day_loss_acc = D0

    for (year, month) in sorted(keys):
        m = MonthlyApuracao(year=year, month=month)

        # Day trade
        m.day_result = sum((r.net_result for r in day_results
                            if (r.trade_date.year, r.trade_date.month) == (year, month)), D0)

        # Swing: separa ações à vista (elegíveis à isenção) das demais operações
        month_sales = [s for s in swing_sales
                       if (s.trade_date.year, s.trade_date.month) == (year, month)]
        equity_sales = [s for s in month_sales if s.market in EQUITY_MARKETS]
        other_sales = [s for s in month_sales if s.market not in EQUITY_MARKETS]

        equity_gross = sum((s.gross for s in equity_sales), D0)
        equity_result = sum((s.result for s in equity_sales), D0)
        other_result = sum((s.result for s in other_sales), D0)

        m.swing_result = equity_result + other_result
        m.equity_swing_gross = equity_gross

        if equity_gross <= ISENCAO_SWING_MENSAL:
            # Vendas de ações à vista isentas: lucro não tributa; prejuízo não compensa.
            m.exempt_result = equity_result
            swing_base = other_result
        else:
            m.exempt_result = D0
            swing_base = equity_result + other_result

        # IRRF retido no mês
        m.irrf_day = sum((_d(n.irrf_day) for n in notes
                          if (n.trade_date.year, n.trade_date.month) == (year, month)), D0)
        m.irrf_swing = sum((_d(n.irrf_swing) for n in notes
                            if (n.trade_date.year, n.trade_date.month) == (year, month)), D0)

        # --- Compensação de prejuízo (buckets separados) ---
        # Day
        if m.day_result >= 0:
            used = min(m.day_result, day_loss_acc)
            m.day_taxable_base = m.day_result - used
            m.day_loss_used = used
            day_loss_acc -= used
        else:
            m.day_taxable_base = D0
            day_loss_acc += -m.day_result
        m.day_loss_acc = day_loss_acc

        # Swing (sobre a base já líquida da isenção)
        if swing_base >= 0:
            used = min(swing_base, swing_loss_acc)
            m.swing_taxable_base = swing_base - used
            m.swing_loss_used = used
            swing_loss_acc -= used
        else:
            m.swing_taxable_base = D0
            swing_loss_acc += -swing_base
        m.swing_loss_acc = swing_loss_acc

        # --- Impostos ---
        m.day_tax = money(m.day_taxable_base * ALIQ_DAY)
        m.swing_tax = money(m.swing_taxable_base * ALIQ_SWING)

        darf_bruto = m.day_tax + m.swing_tax
        irrf_total = m.irrf_day + m.irrf_swing
        darf_liquido = darf_bruto - irrf_total
        m.darf = money(max(D0, darf_liquido))
        m.darf_below_min = D0 < m.darf < DARF_MINIMO

        months.append(m)

    return months


# --------------------------------------------------------------------------- #
# Orquestrador
# --------------------------------------------------------------------------- #
def compute(notes) -> ApuracaoResult:
    """Calcula tudo a partir das notas de um usuário.

    Notas BOVESPA (ações) passam pelo preço médio / day-swing por preço.
    Notas BM&F (futuros) já trazem o resultado em ajuste (R$), então o
    resultado de day trade / normal é lançado direto (sem preço médio)."""
    notes = list(notes)
    bovespa = [n for n in notes if (getattr(n, "segment", "BOVESPA") or "BOVESPA") != "BMF"]
    bmf = [n for n in notes if (getattr(n, "segment", "BOVESPA") or "BOVESPA") == "BMF"]

    legs = build_legs(bovespa)
    day_results, swing_legs = split_day_swing(legs)
    positions, swing_sales = run_positions(swing_legs)

    # BM&F: resultado vem do ajuste pré-apurado na própria nota
    for n in bmf:
        dg = _d(getattr(n, "daytrade_gross", 0))
        ng = _d(getattr(n, "normal_gross", 0))
        costs = _d(n.total_costs)
        total_abs = abs(dg) + abs(ng)
        day_costs = (costs * abs(dg) / total_abs) if total_abs > 0 else costs
        normal_costs = costs - day_costs
        ticker = n.trades[0].asset if n.trades else "FUTURO"
        if dg != 0 or (ng == 0 and n.trades):
            day_results.append(DayTradeResult(
                asset=ticker, trade_date=n.trade_date, qty=_d(1),
                avg_buy=D0, avg_sell=D0, gross_result=dg,
                costs=day_costs, net_result=dg - day_costs, market="FUTURO"))
        if ng != 0:
            swing_sales.append(SwingSale(
                asset=ticker, trade_date=n.trade_date, qty=_d(1),
                sell_price=D0, avg_price=D0, proceeds=ng - normal_costs,
                gross=abs(ng), result=ng - normal_costs, market="FUTURO"))

    months = monthly_apuracao(day_results, swing_sales, notes)
    final_day = months[-1].day_loss_acc if months else D0
    final_swing = months[-1].swing_loss_acc if months else D0
    return ApuracaoResult(
        months=months,
        positions=sorted(positions, key=lambda p: p.asset),
        day_results=day_results,
        swing_sales=swing_sales,
        final_day_loss=final_day,
        final_swing_loss=final_swing,
    )
