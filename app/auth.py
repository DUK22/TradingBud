"""Blueprint de autenticação (multi-usuário / SaaS).

Inclui cadastro, login/logout, verificação de e-mail e reset de senha por
token assinado (stateless, expira). Os e-mails saem via services.mailer —
sem MAIL_SERVER configurado, o link é registrado no log (modo dev)."""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length

from .extensions import db, limiter
from .models import User
from .services import mailer, tokens

auth_bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    """Valida o parâmetro ?next= contra open redirect: só aceita caminhos
    relativos dentro da própria aplicação (sem esquema/host)."""
    if not target:
        return None
    url = urlsplit(target)
    if url.scheme or url.netloc:
        return None
    if not url.path.startswith("/") or url.path.startswith("//"):
        return None
    return target


def _send_verification(user: User):
    token = tokens.generate(user.id, tokens.SALT_VERIFY)
    link = url_for("auth.verify_email", token=token, _external=True)
    mailer.send(
        user.email,
        "IR Traders — confirme seu e-mail",
        f"Olá, {user.name}!\n\n"
        f"Confirme seu e-mail clicando no link abaixo (válido por 7 dias):\n\n"
        f"{link}\n\n"
        f"Se você não criou esta conta, ignore esta mensagem.",
    )


class RegistrationForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=120)])
    email = StringField("E-mail", validators=[DataRequired(), Email(), Length(max=255)])
    cpf = StringField("CPF", validators=[Length(max=14)])
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirmar senha",
        validators=[DataRequired(), EqualTo("password", message="As senhas não conferem.")],
    )


class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired()])
    remember = BooleanField("Manter conectado")


class ForgotPasswordForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])


class ResetPasswordForm(FlaskForm):
    password = PasswordField("Nova senha", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirmar nova senha",
        validators=[DataRequired(), EqualTo("password", message="As senhas não conferem.")],
    )


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("Já existe uma conta com esse e-mail.", "error")
        else:
            user = User(
                name=form.name.data.strip(),
                email=form.email.data.lower().strip(),
                cpf=(form.cpf.data or "").strip() or None,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            _send_verification(user)
            flash("Conta criada com sucesso. Enviamos um link de confirmação "
                  "para o seu e-mail.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            nxt = request.args.get("next")
            return redirect(_safe_next(nxt) or url_for("main.dashboard"))
        flash("E-mail ou senha inválidos.", "error")
    return render_template("login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada.", "success")
    return redirect(url_for("auth.login"))


# --------------------------------------------------------------------------- #
# Verificação de e-mail
# --------------------------------------------------------------------------- #
@auth_bp.route("/verificar-email/<token>")
def verify_email(token):
    uid = tokens.verify(token, tokens.SALT_VERIFY, tokens.MAX_AGE_VERIFY)
    user = db.session.get(User, uid) if uid else None
    if not user:
        flash("Link de verificação inválido ou expirado. Peça um novo.", "error")
        return redirect(url_for("main.dashboard")
                        if current_user.is_authenticated else url_for("auth.login"))
    if not user.email_verified:
        user.email_verified = True
        db.session.commit()
    flash("E-mail confirmado. Obrigado!", "success")
    return redirect(url_for("main.dashboard")
                    if current_user.is_authenticated else url_for("auth.login"))


@auth_bp.route("/reenviar-verificacao", methods=["POST"])
@login_required
@limiter.limit("3 per hour")
def resend_verification():
    if current_user.email_verified:
        flash("Seu e-mail já está confirmado.", "success")
    else:
        _send_verification(current_user)
        flash("Link de confirmação reenviado. Confira sua caixa de entrada "
              "(e o spam).", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


# --------------------------------------------------------------------------- #
# Reset de senha
# --------------------------------------------------------------------------- #
@auth_bp.route("/esqueci-senha", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user:
            token = tokens.generate(user.id, tokens.SALT_RESET)
            link = url_for("auth.reset_password", token=token, _external=True)
            mailer.send(
                user.email,
                "IR Traders — redefinição de senha",
                f"Olá, {user.name}!\n\n"
                f"Para redefinir sua senha, acesse o link abaixo (válido por 1 hora):\n\n"
                f"{link}\n\n"
                f"Se você não pediu a redefinição, ignore esta mensagem — sua "
                f"senha continua a mesma.",
            )
        # Mensagem idêntica com ou sem conta: não revela e-mails cadastrados.
        flash("Se houver uma conta com esse e-mail, enviamos um link de "
              "redefinição. Confira sua caixa de entrada.", "success")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html", form=form)


@auth_bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    uid = tokens.verify(token, tokens.SALT_RESET, tokens.MAX_AGE_RESET)
    user = db.session.get(User, uid) if uid else None
    if not user:
        flash("Link de redefinição inválido ou expirado. Peça um novo.", "error")
        return redirect(url_for("auth.forgot_password"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Senha redefinida. Entre com a nova senha.", "success")
        return redirect(url_for("auth.login"))
    return render_template("reset_password.html", form=form, token=token)
