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
