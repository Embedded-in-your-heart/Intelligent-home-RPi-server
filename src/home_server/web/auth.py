"""Authentication blueprint: register, login, logout."""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import UserMixin, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length

from home_server.db import users
from home_server.db.users import DuplicateUsernameError, User
from home_server.services import user_service
from home_server.web.db import get_conn

bp = Blueprint("auth", __name__, url_prefix="/auth")


class LoginUser(UserMixin):
    def __init__(self, user: User) -> None:
        self.user = user

    def get_id(self) -> str:
        return str(self.user.id)

    @property
    def username(self) -> str:
        return self.user.username


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField(
        "Confirm", validators=[DataRequired(), EqualTo("password")]
    )


def _safe_next(target: str | None) -> str:
    # Only allow relative redirects to avoid open-redirect.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


@bp.route("/register", methods=["GET", "POST"])
def register() -> Response | str:
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            uid = user_service.register(
                get_conn(), username=form.username.data, password=form.password.data
            )
        except DuplicateUsernameError:
            flash("Username already taken")
            return render_template("auth/register.html", form=form)
        except user_service.WeakPasswordError:
            flash("Password too weak")
            return render_template("auth/register.html", form=form)
        user = users.get_by_id(get_conn(), uid)
        assert user is not None
        login_user(LoginUser(user))
        return redirect(url_for("index"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login() -> Response | str:
    form = LoginForm()
    if form.validate_on_submit():
        user = user_service.authenticate(
            get_conn(), username=form.username.data, password=form.password.data
        )
        if user is None:
            flash("Invalid username or password")
            return render_template("auth/login.html", form=form)
        login_user(LoginUser(user))
        return redirect(_safe_next(request.args.get("next")))
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout() -> Response:
    logout_user()
    return redirect(url_for("auth.login"))
