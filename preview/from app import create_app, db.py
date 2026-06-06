from app import create_app, db

app = create_app()
with app.app_context():
    try:
        db.engine.execute('ALTER TABLE notes_journal ADD COLUMN analysis_history JSON DEFAULT NULL')
        print("✅ Coluna adicionada com sucesso!")
    except Exception as e:
        print(f"Erro: {e}")
        # Se falhar, tenta com JSON() que é mais genérico
        try:
            db.engine.execute('ALTER TABLE notes_journal ADD COLUMN analysis_history TEXT DEFAULT NULL')
            print("✅ Coluna adicionada como TEXT (será convertida pra JSON)")
        except Exception as e2:
            print(f"Erro final: {e2}")

exit()