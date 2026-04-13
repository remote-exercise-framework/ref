import re

from Crypto.PublicKey import RSA
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_ssh_public_key,
)
from flask import (
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from itsdangerous import URLSafeTimedSerializer
from wtforms import (
    BooleanField,
    Form,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    ValidationError,
    validators,
)

from ref import db, limiter, refbp
from ref.core import UserManager, admin_required, flash
from ref.core.logging import get_logger
from ref.core.util import (
    redirect_to_next,
)
from ref.model import GroupNameList, SystemSettingsManager, User, UserGroup
from ref.model.enums import UserAuthorizationGroups

PASSWORD_MIN_LEN = 8
PASSWORD_SECURITY_LEVEL = 3

# Salt used to sign download links returned to the user.
DOWNLOAD_LINK_SIGN_SALT = "dl-keys"

MAT_REGEX = r"^[0-9]+$"
GROUP_REGEX = r"^[a-zA-Z0-9-_]+$"

log = get_logger(__name__)


class StringFieldDefaultEmpty(StringField):
    def __init__(self, *args, **kwargs):
        if "default" not in kwargs:
            kwargs["default"] = ""
        super().__init__(*args, **kwargs)


def field_to_str(form, field):
    del form
    return str(field.data)


def validate_password(form, field):
    """
    Implements a simple password policy.
    Raises:
        ValidationError: If the password does not fullfill the policy.
    """
    del form
    password = field.data

    if len(password) < PASSWORD_MIN_LEN:
        raise ValidationError(
            f"Password must be at least {PASSWORD_MIN_LEN} characters long."
        )

    digit = re.search(r"\d", password) is not None
    upper = re.search(r"[A-Z]", password) is not None
    lower = re.search(r"[a-z]", password) is not None
    special = re.search(r"[ !#$%&'()*+,-./[\\\]^_`{|}~" + r'"]', password) is not None

    if sum([digit, upper, lower, special]) < PASSWORD_SECURITY_LEVEL:
        raise ValidationError(
            "Password not strong enough. Try to use a mix of digits, upper- and lowercase letters."
        )


def validate_pubkey(form, field):
    """
    Validates an SSH key in the OpenSSH format. Supports RSA, ed25519, and ECDSA keys.
    If the passed field was left empty, validation is also successful since in this
    case we generate a public/private key pair.
    Raises:
         ValidationError: If the key could not be parsed.
    """
    del form
    if field.data is None or field.data == "":
        return

    pubkey_str = field.data.strip()

    # Try RSA first (using pycryptodome)
    try:
        key = RSA.import_key(pubkey_str)
        field.data = key.export_key(format="OpenSSH").decode()
        return field.data
    except (ValueError, IndexError, TypeError):
        pass

    # Try ed25519/ECDSA using cryptography library
    try:
        key = load_ssh_public_key(pubkey_str.encode())
        openssh_bytes = key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
        field.data = openssh_bytes.decode()
        return field.data
    except Exception:
        pass

    log.info(f"Invalid public-key {field.data}.")
    raise ValidationError("Invalid Public-Key.")


class EditUserForm(Form):
    id = IntegerField("ID")
    mat_num = StringFieldDefaultEmpty(
        "Matriculation Number",
        validators=[
            validators.DataRequired(),
            validators.Regexp(MAT_REGEX),
            # FIXME: Field is implemented as number field in the view.
            field_to_str,
        ],
    )
    firstname = StringFieldDefaultEmpty(
        "Firstname", validators=[validators.DataRequired()]
    )
    surname = StringFieldDefaultEmpty("Surname", validators=[validators.DataRequired()])
    auth_group = SelectMultipleField(
        "Authorization Groups",
        choices=[(e.value, e.value) for e in UserAuthorizationGroups],
    )
    group = SelectField(
        "Group",
        choices=[],
        validate_choice=False,
        default="",
    )
    password = PasswordField("Password", default="")
    password_rep = PasswordField("Password (Repeat)", default="")
    is_admin = BooleanField("Is Admin?")
    pubkey = StringFieldDefaultEmpty(
        "Pubkey", validators=[validators.DataRequired(), validate_pubkey]
    )

    submit = SubmitField("Update")


class GetKeyForm(Form):
    mat_num = StringFieldDefaultEmpty(
        "Matriculation Number",
        validators=[
            validators.DataRequired(),
            validators.Regexp(MAT_REGEX),
            field_to_str,
        ],
    )
    firstname = StringFieldDefaultEmpty(
        "Firstname", validators=[validators.DataRequired()], default=""
    )
    surname = StringFieldDefaultEmpty("Surname", validators=[validators.DataRequired()])
    password = PasswordField(
        "Password",
        validators=[validators.DataRequired(), validate_password],
        default="",
    )
    password_rep = PasswordField(
        "Password (Repeat)",
        validators=[validators.DataRequired(), validate_password],
        default="",
    )
    pubkey = StringFieldDefaultEmpty(
        "Public SSH Key (if empty, an Ed25519 key-pair is generated for you)",
        validators=[validate_pubkey],
    )
    group_name = SelectField(
        "Group Name",
        choices=[],
        validate_choice=False,
        default="",
    )
    submit = SubmitField("Get Key")


class RestoreKeyForm(Form):
    mat_num = StringFieldDefaultEmpty(
        "Matriculation Number",
        validators=[
            validators.DataRequired(),
            validators.Regexp(MAT_REGEX),
            field_to_str,  # FIXME: Field is implemented as number in view.
        ],
    )
    password = PasswordField(
        "Password (The password used during first retrieval)",
        validators=[validators.DataRequired()],
        default="",
    )
    submit = SubmitField("Restore")


@refbp.route("/student/download/pubkey/<string:signed_mat>")
@limiter.limit("16 per minute;1024 per day")
def student_download_pubkey(signed_mat: str):
    """
    Returns the public key of the given matriculation number as
    text/plain.
    Args:
        signed_mat: The signed matriculation number.
    """
    signer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt=DOWNLOAD_LINK_SIGN_SALT
    )
    try:
        mat_num = signer.loads(signed_mat, max_age=60 * 10)
    except Exception:
        log.warning("Invalid signature", exc_info=True)
        abort(400)

    student = User.query.filter(User.mat_num == mat_num).one_or_none()
    if student:
        return Response(
            student.pub_key,
            mimetype="text/plain",
            headers={"Content-disposition": "attachment; filename=id_rsa.pub"},
        )

    flash.error("Unknown student")
    abort(400)


@refbp.route("/student/download/privkey/<string:signed_mat>")
@limiter.limit("16 per minute;1024 per day")
def student_download_privkey(signed_mat: str):
    """
    Returns the private key of the given matriculation number as
    text/plain.
    Args:
        signed_mat: The signed matriculation number.
    """
    signer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt=DOWNLOAD_LINK_SIGN_SALT
    )
    try:
        mat_num = signer.loads(signed_mat, max_age=60 * 10)
    except Exception:
        log.warning("Invalid signature", exc_info=True)
        abort(400)

    student = User.query.filter(User.mat_num == mat_num).one_or_none()
    if student:
        return Response(
            student.priv_key,
            mimetype="text/plain",
            headers={"Content-disposition": "attachment; filename=id_rsa"},
        )

    flash.error("Unknown student")
    abort(400)


@refbp.route("/student/getkey", methods=("GET", "POST"))
@limiter.limit("16 per minute;1024 per day")
def student_getkey():
    """
    Endpoint used to genereate a public/private key pair used by the students
    for authentication to get access to the exercises.
    """

    regestration_enabled = SystemSettingsManager.REGESTRATION_ENABLED.value
    if not regestration_enabled:
        flash.warning(
            "Regestration is currently disabled. Please contact the staff if you need to register."
        )
        # Fallthrough

    form = GetKeyForm(request.form)

    groups_enabled = SystemSettingsManager.GROUPS_ENABLED.value
    max_group_size = SystemSettingsManager.GROUP_SIZE.value
    allowed_names: dict[str, GroupNameList] = {}
    group_choices: list[dict] = []
    if groups_enabled:
        for lst in GroupNameList.query.filter(
            GroupNameList.enabled_for_registration.is_(True)
        ).all():
            for n in lst.names or []:
                allowed_names.setdefault(n, lst)
        form.group_name.choices = [(n, n) for n in allowed_names]

        # Per-name current occupancy for the datalist hints.
        existing_groups = {
            g.name: g
            for g in UserGroup.query.filter(
                UserGroup.name.in_(allowed_names.keys())
            ).all()
        }
        for name in allowed_names:
            existing = existing_groups.get(name)
            count = len(existing.users) if existing else 0
            group_choices.append(
                {
                    "name": name,
                    "count": count,
                    "max": max_group_size,
                    "full": count >= max_group_size,
                }
            )

    pubkey = None
    privkey = None
    signed_mat = None
    student = None

    def render():
        return render_template(
            "student_getkey.html",
            route_name="get_key",
            form=form,
            student=student,
            pubkey=pubkey,
            privkey=privkey,
            signed_mat=signed_mat,
            groups_enabled=groups_enabled,
            group_choices=group_choices,
            max_group_size=max_group_size,
        )

    if regestration_enabled and form.submit.data and form.validate():
        # Check if the matriculation number is already registered.
        existing_student = User.query.filter(
            User.mat_num == form.mat_num.data
        ).one_or_none()
        if existing_student:
            form.mat_num.errors += [
                "Already registered, please use your password to restore the key."
            ]
            return render()

        # Check if the pubkey is already regsitered.
        if form.pubkey.data:
            # NOTE: The .data was validated by the form.
            pubkey = form.pubkey.data

            # Check for duplicated key
            existing_student = User.query.filter(User.pub_key == pubkey).one_or_none()
            if existing_student:
                form.pubkey.errors += [
                    "Already registered, please use your password to restore the key."
                ]
                return render()

        # Check password fields
        if form.password.data != form.password_rep.data:
            err = ["Passwords do not match!"]
            form.password.errors += err
            form.password_rep.errors += err
            form.password.data = ""
            form.password_rep.data = ""
            return render()

        # If a public key was provided use it, if not, generate a key pair.
        if form.pubkey.data:
            pubkey = form.pubkey.data
            privkey = None
        else:
            key = Ed25519PrivateKey.generate()
            pubkey = (
                key.public_key()
                .public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
                .decode()
            )
            privkey = key.private_bytes(
                Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
            ).decode()

        group: UserGroup | None = None
        if groups_enabled:
            submitted_name = (form.group_name.data or "").strip()
            if not submitted_name:
                form.group_name.errors = list(form.group_name.errors or []) + [
                    "Please pick a group name."
                ]
                return render()
            if submitted_name not in allowed_names:
                form.group_name.errors = list(form.group_name.errors or []) + [
                    "Pick a name from the offered list."
                ]
                return render()

            source_list = allowed_names[submitted_name]
            existing = (
                UserGroup.query.filter(UserGroup.name == submitted_name)
                .with_for_update()
                .one_or_none()
            )
            if existing is None:
                group = UserGroup()
                group.name = submitted_name
                group.source_list_id = source_list.id
                db.session.add(group)
                db.session.flush()
            else:
                if len(existing.users) >= max_group_size:
                    form.group_name.errors = list(form.group_name.errors or []) + [
                        f"Group '{submitted_name}' is full ({len(existing.users)} / {max_group_size})."
                    ]
                    db.session.rollback()
                    return render()
                group = existing

        student = UserManager.create_student(
            mat_num=form.mat_num.data,
            first_name=form.firstname.data,
            surname=form.surname.data,
            password=form.password.data,
            pub_key=pubkey,
            priv_key=privkey,
            group=group,
        )

        signer = URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"], salt=DOWNLOAD_LINK_SIGN_SALT
        )
        signed_mat = signer.dumps(str(student.mat_num))

        db.session.add(student)
        db.session.commit()

        return render()

    return render()


@refbp.route("/student/restoreKey", methods=("GET", "POST"))
@limiter.limit("16 per minute;1024 per day")
def student_restorekey():
    """
    This endpoint allows a user to restore its key using its matriculation number
    and password that was initially used to create the account.
    """
    form = RestoreKeyForm(request.form)
    pubkey = None
    privkey = None
    signed_mat = None

    def render():
        return render_template(
            "student_restorekey.html",
            route_name="restore_key",
            form=form,
            pubkey=pubkey,
            privkey=privkey,
            signed_mat=signed_mat,
        )

    signer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt=DOWNLOAD_LINK_SIGN_SALT
    )

    if form.submit.data and form.validate():
        student = User.query.filter(User.mat_num == form.mat_num.data).one_or_none()
        if student:
            if student.check_password(form.password.data):
                signed_mat = signer.dumps(str(student.mat_num))
                pubkey = student.pub_key
                privkey = student.priv_key
                return render()
            else:
                form.password.errors += [
                    "Wrong password or matriculation number unknown."
                ]
                return render()
        else:
            form.password.errors += ["Wrong password or matriculation number unknown."]
            return render()

    return render()


@refbp.route("/admin/student/view", methods=("GET", "POST"))
@admin_required
def student_view_all():
    """
    List all students currently registered.
    """
    students = User.query.order_by(User.id).all()
    return render_template(
        "student_view_all.html",
        students=students,
        max_group_size=SystemSettingsManager.GROUP_SIZE.value,
    )


@refbp.route("/admin/student/view/<int:user_id>")
@admin_required
def student_view_single(user_id):
    """
    Shows details for the user that belongs to the given user_id.
    """
    user = User.query.filter(User.id == user_id).one_or_none()
    if not user:
        flash.error(f"Unknown user ID {user_id}")
        abort(400)

    return render_template("student_view_single.html", user=user)


@refbp.route("/admin/student/edit/<int:user_id>", methods=("GET", "POST"))
@admin_required
def student_edit(user_id):
    """
    Edit the user with the id user_id.
    """
    form = EditUserForm(request.form)

    user: User = User.query.filter(User.id == user_id).one_or_none()
    if not user:
        flash.error(f"Unknown user ID {user_id}")
        abort(400)

    all_groups = UserGroup.query.order_by(UserGroup.name).all()
    existing_group_names = {g.name for g in all_groups}
    enabled_lists = GroupNameList.query.filter(
        GroupNameList.enabled_for_registration.is_(True)
    ).all()
    predefined_names: dict[str, GroupNameList] = {}
    for lst in enabled_lists:
        for n in lst.names or []:
            predefined_names.setdefault(n, lst)

    max_group_size_edit = SystemSettingsManager.GROUP_SIZE.value
    choices: list[tuple[str, str]] = [("", "— none —")]
    for g in all_groups:
        choices.append((g.name, f"{g.name} ({len(g.users)}/{max_group_size_edit})"))
    for n in predefined_names:
        if n not in existing_group_names:
            choices.append((n, f"{n} (new, 0/{max_group_size_edit})"))
    form.group.choices = choices

    if form.submit.data and form.validate():
        # Form was submitted

        if form.password.data != "":
            if form.password.data != form.password_rep.data:
                form.password.errors += ["Passwords do not match"]
                return render_template("user_edit.html", form=form)
            else:
                user.set_password(form.password.data)
                user.invalidate_session()

        mat_num = form.mat_num.data
        if User.query.filter(User.mat_num == mat_num).one_or_none() not in [None, user]:
            form.mat_num.errors += ["Already taken"]
            return render_template("user_edit.html", form=form)

        pubkey = form.pubkey.data
        if User.query.filter(User.pub_key == pubkey).one_or_none() not in [None, user]:
            form.pubkey.errors += ["Already taken"]
            return render_template("user_edit.html", form=form)

        user.mat_num = mat_num
        user.first_name = form.firstname.data
        user.surname = form.surname.data
        user.pub_key = form.pubkey.data

        # Invalidate login if the authentication group changed
        new_auth_groups = set()
        assert form.auth_group.data is not None
        for auth_group in form.auth_group.data:
            new_auth_groups.add(UserAuthorizationGroups(auth_group))
        if new_auth_groups != set(user.auth_groups):
            user.invalidate_session()
        user.auth_groups = list(new_auth_groups)

        target_name = (form.group.data or "").strip()
        if target_name == "":
            user.group = None
        else:
            target = (
                UserGroup.query.filter(UserGroup.name == target_name)
                .with_for_update()
                .one_or_none()
            )
            if target is None:
                if target_name not in predefined_names:
                    form.group.errors = list(form.group.errors or []) + [
                        "Unknown group"
                    ]
                    return render_template("user_edit.html", form=form)
                target = UserGroup()
                target.name = target_name
                target.source_list_id = predefined_names[target_name].id
                current_app.db.session.add(target)
                current_app.db.session.flush()
            moving_in = user.group is None or user.group.id != target.id
            if moving_in and len(target.users) >= max_group_size_edit:
                form.group.errors = list(form.group.errors or []) + [
                    f"Group '{target.name}' is full ({len(target.users)} / {max_group_size_edit})."
                ]
                current_app.db.session.rollback()
                return render_template("user_edit.html", form=form)
            user.group = target

        current_app.db.session.add(user)
        current_app.db.session.commit()

        flash.success("Updated!")
        return render_template("user_edit.html", form=form)
    else:
        # Form was not submitted: Set initial values
        form.id.data = user.id
        form.mat_num.data = user.mat_num
        form.firstname.data = user.first_name
        form.surname.data = user.surname
        form.pubkey.data = user.pub_key
        form.auth_group.data = [e.value for e in user.auth_groups]
        form.group.data = user.group.name if user.group else ""
        # Leave password empty
        form.password.data = ""
        form.password_rep.data = ""

    return render_template("user_edit.html", form=form)


@refbp.route("/admin/student/delete/<int:user_id>")
@admin_required
def student_delete(user_id):
    """
    Deletes the given user.
    """
    user: User = User.query.filter(User.id == user_id).one_or_none()

    if not user:
        flash.warning(f"Unknown user ID {user_id}")
        return redirect_to_next()

    if user.is_admin:
        flash.warning("Admin users can not be deleted")
        return redirect_to_next()

    if len(user.exercise_instances) > 0:
        flash.error("User has active instances, please delete them first!")
        return redirect_to_next()

    current_app.db.session.delete(user)
    current_app.db.session.commit()
    flash.success(f"User {user.id} deleted")

    return redirect_to_next()


@refbp.route("/student/")
@refbp.route("/student")
@refbp.route("/")
def student_default_routes():
    """
    Redirect some urls to the key retrival form.
    """
    return redirect(url_for("ref.student_getkey"))
