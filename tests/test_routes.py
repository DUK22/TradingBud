"""Testes de rotas: paginação das listagens."""
from datetime import date

from app.extensions import db
from app.models import BrokerageNote


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_paginacao_notas(app, client, user):
    original = app.config["ITEMS_PER_PAGE"]
    app.config["ITEMS_PER_PAGE"] = 2
    try:
        for i in range(3):  # 3 notas, 2 por página => 2 páginas
            db.session.add(BrokerageNote(user_id=user.id, broker="T",
                                         trade_date=date(2026, 1, i + 1), source="MANUAL"))
        db.session.commit()
        _login(client)

        p1 = client.get("/notas").get_data(as_text=True)
        assert "Próxima" in p1
        assert "página 1 de 2" in p1

        p2 = client.get("/notas?page=2").get_data(as_text=True)
        assert "Anterior" in p2

        # Página fora do intervalo não deve dar erro (error_out=False)
        assert client.get("/notas?page=99").status_code == 200
    finally:
        app.config["ITEMS_PER_PAGE"] = original


def test_drilldown_apuracao_mes(client, user):
    """Página do mês lista as operações que compõem a base."""
    from datetime import date
    from decimal import Decimal

    from app.extensions import db
    from app.models import BrokerageNote, Trade

    client.post("/login", data={"email": "t@t.com", "password": "password"})
    for d, side, qty, price in [(date(2026, 5, 5), "C", 100, 10),
                                (date(2026, 5, 5), "V", 100, 12),     # day trade
                                (date(2026, 5, 6), "C", 50, 20),
                                (date(2026, 5, 20), "V", 50, 25)]:    # swing
        n = BrokerageNote(user_id=user.id, broker="T", trade_date=d, source="MANUAL")
        db.session.add(n)
        db.session.flush()
        db.session.add(Trade(user_id=user.id, note_id=n.id, trade_date=d, asset="XPTO3",
                             market="VISTA", side=side, quantity=Decimal(qty),
                             price=Decimal(price), gross_value=Decimal(qty * price)))
    db.session.commit()

    r = client.get("/apuracao/2026/5")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Day trades" in html and "Vendas de swing" in html
    assert html.count("XPTO3") >= 2          # aparece nas duas tabelas
    assert client.get("/apuracao/2030/1").status_code == 404
