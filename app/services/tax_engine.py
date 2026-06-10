"""Engine de cálculo de IR para renda variável (pessoa física).

Responsabilidades:
  1. Alocar os custos da nota (corretagem, emolumentos, ISS...) a cada negócio,
     proporcionalmente ao volume financeiro.
  2. Separar automaticamente DAY TRADE de SWING TRADE por (ativo, dia):
     day trade = quantidade que foi comprada E vendida do mesmo ativo no mesmo dia.
  3. Calcular o PREÇO MÉDIO PONDERADO das posições de swing (custo de aquisição
     inclui as taxas; a venda é líquida das taxas), aplicando eventos
     corporativos (desdobramento, grupamento, bonificação) na data correta.
  4. Apurar mês a mês por CLASSE DE ATIVO:
       - Ações/Units: 15% swing com isenção de R$20k (vendas à vista), 20% day.
       - FIIs: 20% (swing e day), sem isenção, bucket próprio de prejuízo.
       - ETFs RV e BDRs: 15% swing SEM isenção, 20% day.
       - ETFs de renda fixa: IR na fonte — excluídos da apuração (com aviso).
     Compensação de prejuízos em buckets separados (day / swing / FII), IRRF
     retido compensado por modalidade (day x demais) com crédito acumulável, e
     DARF (código 6015) com regra do mínimo de R$10 (acumula p/ mês seguinte).

IMPORTANTE: implementação para fins de organização/estimativa. Não substitui
a conferência de um contador. Regras simplificadas estão sinalizadas no código.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from . import asset_classes

D0 = Decimal("0")
CENT = Decimal("0.01")

# --- Parâmetros fiscais (renda variável PF) ---
ALIQ_SWING = Decimal("0.15")          # 15% sobre o ganho líquido em swing trade
ALIQ_DAY = Decimal("0.20")            # 20% sobre o ganho líquido em day trade
ALIQ_FII = Decimal("0.20")            # 20% sobre ganhos com FII (swing e day)
ISENCAO_SWING_MENSAL = Decimal("20000")   # isenção p/ vendas à vista de ações no swing
DARF_MINIMO = Decimal("10")           # DARF abaixo disso é acumulado p/ meses seguintes
DARF_CODIGO = "6015"                  # ganhos líquidos em renda variável - PF

# Mercados elegíveis à isenção mensal de R$20k (ações à vista)
EQUITY_MARKETS = {"VISTA", "FRACIONARIO"}

# Tipos de evento corporativo suportados
ADJ_SPLIT = "DESDOBRAMENTO"     # 1 -> N (factor = N, ex.: 10)
ADJ_INPLIT = "GRUPAMENTO"       # N -> 1 (factor = novas/antigas, ex.: 0.1)
ADJ_BONUS = "BONIFICACAO"       # recebe qty ações ao custo unitário price


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
    swing_result: Decimal = D0           # swing de ações/units/ETFs/BDRs (antes de isenção)
    fii_result: Decimal = D0             # FIIs (swing + day) — bucket próprio, 20%
    equity_swing_gross: Decimal = D0     # vendas à vista de ações (teste dos 20k)
    exempt_result: Decimal = D0          # parcela isenta (ações à vista <= 20k)
    # bases tributáveis após isenção e compensação
    swing_taxable_base: Decimal = D0
    day_taxable_base: Decimal = D0
    fii_taxable_base: Decimal = D0
    swing_loss_used: Decimal = D0
    day_loss_used: Decimal = D0
    fii_loss_used: Decimal = D0
    swing_loss_acc: Decimal = D0         # prejuízo acumulado APÓS o mês
    day_loss_acc: Decimal = D0
    fii_loss_acc: Decimal = D0
    # impostos
    swing_tax: Decimal = D0
    day_tax: Decimal = D0
    fii_tax: Decimal = D0
    irrf_day: Decimal = D0               # retido no mês (1% day trade)
    irrf_swing: Decimal = D0             # retido no mês (0,005% "dedo-duro")
    irrf_day_used: Decimal = D0          # crédito de IRRF day abatido neste mês
    irrf_swing_used: Decimal = D0        # crédito de IRRF swing abatido neste mês
    darf_carried_in: Decimal = D0        # DARF < R$10 acumulado de meses anteriores
    darf: Decimal = D0                   # valor a recolher NESTE mês (0 se < mínimo)
    darf_below_min: bool = False         # True => valor acumulou p/ mês seguinte

    @property
    def total_result(self) -> Decimal:
        return self.day_result + self.swing_result + self.fii_result

    @property
    def total_tax(self) -> Decimal:
        return self.swing_tax + self.day_tax + self.fii_tax


@dataclass
class ApuracaoResult:
    months: list = field(default_factory=list)        # list[MonthlyApuracao]
    positions: list = field(default_factory=list)     # list[Position]
    day_results: list = field(default_factory=list)
    swing_sales: list = field(default_factory=list)
    final_day_loss: Decimal = D0
    final_swing_loss: Decimal = D0
    final_fii_loss: Decimal = D0
    warnings: list = field(default_factory=list)      # avisos p/ o usuário (UI)

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
        buys = [lg for lg in group if lg.side == "C"]
        sells = [lg for lg in group if lg.side == "V"]
        buy_qty = sum((lg.qty for lg in buys), D0)
        sell_qty = sum((lg.qty for lg in sells), D0)
        dt_qty = min(buy_qty, sell_qty)
        group_costs = sum((lg.costs for lg in group), D0)
        market = group[0].market

        if dt_qty <= 0:
            swing_legs.extend(group)
            continue

        buy_val = sum((lg.qty * lg.price for lg in buys), D0)
        sell_val = sum((lg.qty * lg.price for lg in sells), D0)
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
# 3. Preço médio ponderado (posições de swing) + eventos corporativos
# --------------------------------------------------------------------------- #
def _apply_adjustment(pos: Position, adj, warnings: list):
    """Aplica um evento corporativo à posição aberta."""
    kind = getattr(adj, "kind", "")
    if kind in (ADJ_SPLIT, ADJ_INPLIT):
        factor = _d(getattr(adj, "factor", 0))
        if factor <= 0:
            warnings.append(
                f"Ajuste de {adj.asset} em {adj.event_date:%d/%m/%Y} ignorado: "
                f"fator inválido ({factor}).")
            return
        if pos.qty <= 0:
            warnings.append(
                f"Ajuste de {adj.asset} em {adj.event_date:%d/%m/%Y} ignorado: "
                f"não havia posição aberta na data.")
            return
        pos.qty = pos.qty * factor
        pos.avg_price = (pos.total_cost / pos.qty) if pos.qty > 0 else D0
    elif kind == ADJ_BONUS:
        qty = _d(getattr(adj, "qty", 0))
        price = _d(getattr(adj, "price", 0))
        if qty <= 0:
            warnings.append(
                f"Bonificação de {adj.asset} em {adj.event_date:%d/%m/%Y} ignorada: "
                f"quantidade inválida.")
            return
        pos.qty += qty
        pos.total_cost += qty * price
        pos.avg_price = (pos.total_cost / pos.qty) if pos.qty > 0 else D0
    else:
        warnings.append(f"Tipo de ajuste desconhecido em {adj.asset}: {kind}.")


def run_positions(swing_legs, adjustments=()) -> tuple:
    """Processa legs de swing + eventos corporativos em ordem cronológica.

    Eventos corporativos da data D são aplicados ANTES dos negócios de D.
    Retorna (posições abertas, vendas de swing, avisos)."""
    positions: dict = {}
    swing_sales = []
    warnings: list = []

    # Stream único ordenado: (data, prioridade) — ajustes (-1) < compras (0) < vendas (1)
    events = [(adj.event_date, -1, adj) for adj in (adjustments or [])]
    events += [(lg.trade_date, 0 if lg.side == "C" else 1, lg) for lg in swing_legs]
    events.sort(key=lambda e: (e[0], e[1]))

    for _date, _prio, ev in events:
        if _prio == -1:   # evento corporativo
            pos = positions.get(ev.asset.upper().strip() if ev.asset else "")
            if pos is None:
                warnings.append(
                    f"Ajuste de {ev.asset} em {ev.event_date:%d/%m/%Y} ignorado: "
                    f"não havia posição aberta na data.")
                continue
            _apply_adjustment(pos, ev, warnings)
            continue

        leg = ev
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
            if leg.qty > pos.qty:
                warnings.append(
                    f"Venda a descoberto detectada: {leg.asset} em "
                    f"{leg.trade_date:%d/%m/%Y} (vendeu {leg.qty:f} com posição de "
                    f"{pos.qty:f}). O resultado dessa operação pode estar incorreto — "
                    f"confira se faltam notas de compra anteriores.")
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
    return open_positions, swing_sales, warnings


# --------------------------------------------------------------------------- #
# 4. Apuração mensal com compensação de prejuízo e impostos
# --------------------------------------------------------------------------- #
def _is_fii(asset: str) -> bool:
    return asset_classes.classify(asset) == asset_classes.FII


def _is_exempt_eligible(sale) -> bool:
    """Isenção dos 20k: só AÇÕES (inclui units) negociadas à vista/fracionário."""
    return (sale.market in EQUITY_MARKETS
            and asset_classes.classify(sale.asset) == asset_classes.ACAO)


def monthly_apuracao(day_results, swing_sales, notes, warnings=None) -> list:
    warnings = warnings if warnings is not None else []

    # ETFs de renda fixa têm IR retido na fonte: ficam FORA da apuração mensal.
    rf_assets = sorted({s.asset for s in swing_sales
                        if asset_classes.classify(s.asset) == asset_classes.ETF_RF}
                       | {r.asset for r in day_results
                          if asset_classes.classify(r.asset) == asset_classes.ETF_RF})
    if rf_assets:
        warnings.append(
            "ETF(s) de renda fixa fora da apuração (IR é retido na fonte): "
            + ", ".join(rf_assets) + ".")
        swing_sales = [s for s in swing_sales
                       if asset_classes.classify(s.asset) != asset_classes.ETF_RF]
        day_results = [r for r in day_results
                       if asset_classes.classify(r.asset) != asset_classes.ETF_RF]

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
    fii_loss_acc = D0
    irrf_day_credit = D0      # crédito de IRRF (1% day) ainda não compensado
    irrf_swing_credit = D0    # crédito de IRRF (dedo-duro) ainda não compensado
    darf_pending = D0         # DARF < R$10 acumulado de meses anteriores

    for (year, month) in sorted(keys):
        m = MonthlyApuracao(year=year, month=month)

        def in_month(obj, _ym=(year, month)):
            return (obj.trade_date.year, obj.trade_date.month) == _ym

        # --- FII: bucket próprio (20%, sem isenção; day e swing juntos) ---
        fii_day = [r for r in day_results if in_month(r) and _is_fii(r.asset)]
        fii_sales = [s for s in swing_sales if in_month(s) and _is_fii(s.asset)]
        m.fii_result = (sum((r.net_result for r in fii_day), D0)
                        + sum((s.result for s in fii_sales), D0))

        # --- Day trade (exceto FII) ---
        m.day_result = sum((r.net_result for r in day_results
                            if in_month(r) and not _is_fii(r.asset)), D0)

        # --- Swing (exceto FII): ações têm isenção; ETF/BDR não ---
        month_sales = [s for s in swing_sales if in_month(s) and not _is_fii(s.asset)]
        exempt_eligible = [s for s in month_sales if _is_exempt_eligible(s)]
        other_sales = [s for s in month_sales if not _is_exempt_eligible(s)]

        equity_gross = sum((s.gross for s in exempt_eligible), D0)
        equity_result = sum((s.result for s in exempt_eligible), D0)
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
        irrf_day_credit += m.irrf_day
        irrf_swing_credit += m.irrf_swing

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

        # FII (prejuízo de FII só compensa FII)
        if m.fii_result >= 0:
            used = min(m.fii_result, fii_loss_acc)
            m.fii_taxable_base = m.fii_result - used
            m.fii_loss_used = used
            fii_loss_acc -= used
        else:
            m.fii_taxable_base = D0
            fii_loss_acc += -m.fii_result
        m.fii_loss_acc = fii_loss_acc

        # --- Impostos ---
        m.day_tax = money(m.day_taxable_base * ALIQ_DAY)
        m.swing_tax = money(m.swing_taxable_base * ALIQ_SWING)
        m.fii_tax = money(m.fii_taxable_base * ALIQ_FII)

        # --- IRRF compensado POR MODALIDADE (simplificação documentada):
        #     - 1% day trade abate imposto de day trade;
        #     - 0,005% "dedo-duro" abate imposto das demais operações (swing+FII).
        #     Crédito não usado fica acumulado p/ os meses seguintes (na prática a
        #     RFB limita ao ano-calendário; sobras vão à DIRPF — fora do escopo).
        m.irrf_day_used = min(m.day_tax, irrf_day_credit)
        irrf_day_credit -= m.irrf_day_used
        day_due = m.day_tax - m.irrf_day_used

        other_tax = m.swing_tax + m.fii_tax
        m.irrf_swing_used = min(other_tax, irrf_swing_credit)
        irrf_swing_credit -= m.irrf_swing_used
        other_due = other_tax - m.irrf_swing_used

        # --- DARF do mês (regra do mínimo de R$10: acumula p/ mês seguinte) ---
        m.darf_carried_in = darf_pending
        total_due = money(day_due + other_due) + darf_pending
        if total_due <= D0:
            m.darf = D0
            darf_pending = D0
        elif total_due < DARF_MINIMO:
            m.darf = D0
            m.darf_below_min = True
            darf_pending = total_due
        else:
            m.darf = total_due
            darf_pending = D0

        months.append(m)

    return months


# --------------------------------------------------------------------------- #
# Orquestrador
# --------------------------------------------------------------------------- #
def compute(notes, adjustments=()) -> ApuracaoResult:
    """Calcula tudo a partir das notas (e eventos corporativos) de um usuário.

    Notas BOVESPA (ações) passam pelo preço médio / day-swing por preço.
    Notas BM&F (futuros) já trazem o resultado em ajuste (R$), então o
    resultado de day trade / normal é lançado direto (sem preço médio)."""
    notes = list(notes)
    bovespa = [n for n in notes if (getattr(n, "segment", "BOVESPA") or "BOVESPA") != "BMF"]
    bmf = [n for n in notes if (getattr(n, "segment", "BOVESPA") or "BOVESPA") == "BMF"]

    legs = build_legs(bovespa)
    day_results, swing_legs = split_day_swing(legs)
    positions, swing_sales, warnings = run_positions(swing_legs, adjustments)

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

    months = monthly_apuracao(day_results, swing_sales, notes, warnings)
    final_day = months[-1].day_loss_acc if months else D0
    final_swing = months[-1].swing_loss_acc if months else D0
    final_fii = months[-1].fii_loss_acc if months else D0
    return ApuracaoResult(
        months=months,
        positions=sorted(positions, key=lambda p: p.asset),
        day_results=day_results,
        swing_sales=swing_sales,
        final_day_loss=final_day,
        final_swing_loss=final_swing,
        final_fii_loss=final_fii,
        warnings=warnings,
    )
