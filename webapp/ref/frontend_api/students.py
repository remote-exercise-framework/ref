"""SPA endpoints for student registration and key restoration.

The `signed_mat` returned to the client is signed with the
`URLSafeTimedSerializer(salt=DOWNLOAD_LINK_SIGN_SALT)` defined in
`view/student.py`, which also exposes the
`/student/download/pubkey/<signed_mat>` and
`/student/download/privkey/<signed_mat>` download routes consumed by the
SPA.
"""

import re
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from flask import current_app, request
from itsdangerous import URLSafeTimedSerializer
from wtforms import ValidationError

from ref import db, limiter, refbp
from ref.core import UserManager
from ref.core.logging import get_logger
from ref.model import GroupNameList, SystemSettingsManager, User, UserGroup
from ref.frontend_api import (
    SPA_READ_LIMIT,
    SPA_WRITE_LIMIT,
    spa_api_error,
)
from ref.view.student import (
    DOWNLOAD_LINK_SIGN_SALT,
    MAT_REGEX,
    PASSWORD_MIN_LEN,
    PASSWORD_SECURITY_LEVEL,
    validate_pubkey,
)

log = get_logger(__name__)


# Small shim around the WTForms validators so we can reuse them on plain
# dicts without a Form instance. Both validators only read `field.data` and
# raise ValidationError, so a tiny duck-typed object is enough.
class _Field:
    def __init__(self, data: str) -> None:
        self.data = data


def _run_validator(validator, value: str) -> tuple[str, list[str]]:
    """Run a WTForms validator on a scalar. Returns (normalized_value, errors)."""
    field = _Field(value)
    try:
        validator(None, field)
    except ValidationError as e:
        return value, [str(e)]
    # Some validators (validate_pubkey) rewrite field.data to the normalized
    # OpenSSH form — pick that up.
    return field.data, []


def _check_password(password: str) -> list[str]:
    """SPA password validator that spells out exactly which character
    classes the user is still missing."""
    errors: list[str] = []
    if len(password) < PASSWORD_MIN_LEN:
        errors.append(
            f"Password must be at least {PASSWORD_MIN_LEN} characters long "
            f"(got {len(password)})."
        )

    classes = {
        "digits": re.search(r"\d", password) is not None,
        "uppercase": re.search(r"[A-Z]", password) is not None,
        "lowercase": re.search(r"[a-z]", password) is not None,
        "symbols": re.search(r"[ !#$%&'()*+,\-./\[\\\]^_`{|}~\"]", password)
        is not None,
    }
    have = sum(classes.values())
    if have < PASSWORD_SECURITY_LEVEL:
        missing = [name for name, present in classes.items() if not present]
        needed = PASSWORD_SECURITY_LEVEL - have
        errors.append(
            f"Password must use at least {PASSWORD_SECURITY_LEVEL} of: "
            f"digits, uppercase, lowercase, symbols — add {needed} more "
            f"(missing: {', '.join(missing)})."
        )
    return errors


def _build_group_choices(
    allowed_names: dict[str, GroupNameList], max_group_size: int
) -> list[dict[str, Any]]:
    """Compute per-name occupancy for the SPA registration meta endpoint."""
    existing_groups = {
        g.name: g
        for g in UserGroup.query.filter(UserGroup.name.in_(allowed_names.keys())).all()
    }
    out: list[dict[str, Any]] = []
    for name in allowed_names:
        existing = existing_groups.get(name)
        count = len(existing.users) if existing else 0
        out.append(
            {
                "name": name,
                "count": count,
                "max": max_group_size,
                "full": count >= max_group_size,
            }
        )
    return out


def _signed_mat_for(mat_num: str) -> tuple[str, str, str | None]:
    """Sign the matriculation number and return (signed_mat, pubkey_url,
    privkey_url-or-None)."""
    signer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt=DOWNLOAD_LINK_SIGN_SALT
    )
    signed_mat = signer.dumps(str(mat_num))
    pubkey_url = f"/student/download/pubkey/{signed_mat}"
    privkey_url = f"/student/download/privkey/{signed_mat}"
    return signed_mat, pubkey_url, privkey_url


def _success_payload(student: User, signed_mat: str) -> dict[str, Any]:
    pubkey_url = f"/student/download/pubkey/{signed_mat}"
    privkey_url = (
        f"/student/download/privkey/{signed_mat}" if student.priv_key else None
    )
    return {
        "signed_mat": signed_mat,
        "pubkey": student.pub_key,
        "privkey": student.priv_key,
        "pubkey_url": pubkey_url,
        "privkey_url": privkey_url,
    }


# ---------------------------------------------------------------------------
# GET /api/v2/registration/meta
# ---------------------------------------------------------------------------


@refbp.route("/api/v2/registration/meta", methods=("GET",))
@limiter.limit(SPA_READ_LIMIT)
def spa_api_registration_meta():
    """Metadata the SPA's registration page needs to render its form.

    Shape:

        {
          "course_name": "...",
          "registration_enabled": true,
          "groups_enabled": true,
          "max_group_size": 4,
          "groups": [{"name": "alpha", "count": 2, "max": 4, "full": false}, ...],
          "password_rules": {"min_length": 8, "min_classes": 3},
          "mat_num_regex": "^[0-9]+$"
        }
    """
    groups_enabled = SystemSettingsManager.GROUPS_ENABLED.value
    max_group_size = SystemSettingsManager.GROUP_SIZE.value

    groups: list[dict[str, Any]] = []
    if groups_enabled:
        allowed_names: dict[str, GroupNameList] = {}
        for lst in GroupNameList.query.filter(
            GroupNameList.enabled_for_registration.is_(True)
        ).all():
            for n in lst.names or []:
                allowed_names.setdefault(n, lst)
        groups = _build_group_choices(allowed_names, max_group_size)

    return {
        "course_name": SystemSettingsManager.COURSE_NAME.value,
        "registration_enabled": SystemSettingsManager.REGESTRATION_ENABLED.value,
        "groups_enabled": groups_enabled,
        "max_group_size": max_group_size,
        "groups": groups,
        "password_rules": {
            "min_length": PASSWORD_MIN_LEN,
            "min_classes": PASSWORD_SECURITY_LEVEL,
        },
        "mat_num_regex": MAT_REGEX,
    }, 200


# ---------------------------------------------------------------------------
# POST /api/v2/registration
# ---------------------------------------------------------------------------


@refbp.route("/api/v2/registration", methods=("POST",))
@limiter.limit(SPA_WRITE_LIMIT)
def spa_api_registration():
    """Create a student account and return a signed download token."""
    if not SystemSettingsManager.REGESTRATION_ENABLED.value:
        return spa_api_error("Registration is currently disabled.")

    payload = request.get_json(silent=True) or {}
    fields: dict[str, list[str]] = {}

    mat_num = str(payload.get("mat_num", "") or "").strip()
    firstname = str(payload.get("firstname", "") or "").strip()
    surname = str(payload.get("surname", "") or "").strip()
    password = str(payload.get("password", "") or "")
    password_rep = str(payload.get("password_rep", "") or "")
    pubkey_in = str(payload.get("pubkey", "") or "").strip()
    group_name = str(payload.get("group_name", "") or "").strip()

    # Presence + format checks (mirrors WTForms DataRequired + Regexp).
    if not mat_num:
        fields.setdefault("mat_num", []).append("Matriculation number is required.")
    elif not re.match(MAT_REGEX, mat_num):
        fields.setdefault("mat_num", []).append("Matriculation number must be numeric.")
    if not firstname:
        fields.setdefault("firstname", []).append("Firstname is required.")
    if not surname:
        fields.setdefault("surname", []).append("Surname is required.")
    if not password:
        fields.setdefault("password", []).append("Password is required.")
    if not password_rep:
        fields.setdefault("password_rep", []).append("Password (repeat) is required.")

    if password:
        pw_errs = _check_password(password)
        if pw_errs:
            fields.setdefault("password", []).extend(pw_errs)
    if password and password_rep and password != password_rep:
        err = ["Passwords do not match!"]
        fields.setdefault("password", []).extend(err)
        fields.setdefault("password_rep", []).extend(err)

    normalized_pubkey = ""
    if pubkey_in:
        normalized_pubkey, pk_errs = _run_validator(validate_pubkey, pubkey_in)
        if pk_errs:
            fields.setdefault("pubkey", []).extend(pk_errs)

    if fields:
        return spa_api_error("Validation failed", fields)

    # Uniqueness checks.
    if User.query.filter(User.mat_num == mat_num).one_or_none() is not None:
        return spa_api_error(
            "Validation failed",
            {
                "mat_num": [
                    "Already registered, please use your password to restore the key."
                ]
            },
        )
    if normalized_pubkey:
        if (
            User.query.filter(User.pub_key == normalized_pubkey).one_or_none()
            is not None
        ):
            return spa_api_error(
                "Validation failed",
                {
                    "pubkey": [
                        "Already registered, please use your password to restore the key."
                    ]
                },
            )

    groups_enabled = SystemSettingsManager.GROUPS_ENABLED.value
    max_group_size = SystemSettingsManager.GROUP_SIZE.value
    group: UserGroup | None = None

    if groups_enabled:
        allowed_names: dict[str, GroupNameList] = {}
        for lst in GroupNameList.query.filter(
            GroupNameList.enabled_for_registration.is_(True)
        ).all():
            for n in lst.names or []:
                allowed_names.setdefault(n, lst)

        if group_name:
            # User picked a specific group — honour their choice, and
            # surface errors on the group_name field if it is invalid or
            # full.
            if group_name not in allowed_names:
                return spa_api_error(
                    "Validation failed",
                    {"group_name": ["Pick a name from the offered list."]},
                )
            source_list = allowed_names[group_name]
            existing = (
                UserGroup.query.filter(UserGroup.name == group_name)
                .with_for_update()
                .one_or_none()
            )
            if existing is None:
                group = UserGroup()
                group.name = group_name
                group.source_list_id = source_list.id
                db.session.add(group)
                db.session.flush()
            else:
                if len(existing.users) >= max_group_size:
                    db.session.rollback()
                    return spa_api_error(
                        "Validation failed",
                        {
                            "group_name": [
                                f"Group '{group_name}' is full "
                                f"({len(existing.users)} / {max_group_size})."
                            ]
                        },
                    )
                group = existing
        else:
            # Auto-assign. Prefer filling partially-occupied groups (so
            # slots don't strand on half-full groups) before creating a
            # new UserGroup row from the allowed-names pool. Lock every
            # candidate FOR UPDATE so concurrent registrations can't
            # both pick the same last slot.
            occupied = {
                g.name: g
                for g in UserGroup.query.filter(
                    UserGroup.name.in_(allowed_names.keys())
                )
                .with_for_update()
                .all()
            }
            picked: UserGroup | None = None
            # Prefer the fullest-but-not-full existing group so we pack
            # partially-occupied groups tight before opening new ones.
            candidates = [g for g in occupied.values() if len(g.users) < max_group_size]
            candidates.sort(key=lambda g: (-len(g.users), g.name))
            if candidates:
                picked = candidates[0]
            if picked is None:
                for name, lst in allowed_names.items():
                    if name in occupied:
                        continue
                    picked = UserGroup()
                    picked.name = name
                    picked.source_list_id = lst.id
                    db.session.add(picked)
                    db.session.flush()
                    break
            if picked is None:
                db.session.rollback()
                return spa_api_error(
                    "No group slots are available. Please contact the staff.",
                )
            group = picked

    # Key material: use the supplied pubkey or generate a fresh Ed25519 pair.
    if normalized_pubkey:
        pubkey = normalized_pubkey
        privkey: str | None = None
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

    student = UserManager.create_student(
        mat_num=mat_num,
        first_name=firstname,
        surname=surname,
        password=password,
        pub_key=pubkey,
        priv_key=privkey,
        group=group,
    )
    db.session.add(student)
    db.session.commit()

    signed_mat, _, _ = _signed_mat_for(student.mat_num)
    return _success_payload(student, signed_mat), 200


# ---------------------------------------------------------------------------
# POST /api/v2/restore-key
# ---------------------------------------------------------------------------


@refbp.route("/api/v2/restore-key", methods=("POST",))
@limiter.limit(SPA_WRITE_LIMIT)
def spa_api_restore_key():
    """Return the stored keypair for a student, gated by their password.

    The error message deliberately does not distinguish between a wrong
    password and an unknown mat_num.
    """
    payload = request.get_json(silent=True) or {}
    mat_num = str(payload.get("mat_num", "") or "").strip()
    password = str(payload.get("password", "") or "")

    fields: dict[str, list[str]] = {}
    if not mat_num:
        fields.setdefault("mat_num", []).append("Matriculation number is required.")
    elif not re.match(MAT_REGEX, mat_num):
        fields.setdefault("mat_num", []).append("Matriculation number must be numeric.")
    if not password:
        fields.setdefault("password", []).append("Password is required.")
    if fields:
        return spa_api_error("Validation failed", fields)

    student = User.query.filter(User.mat_num == mat_num).one_or_none()
    if student is None or not student.check_password(password):
        return spa_api_error(
            "Validation failed",
            {"password": ["Wrong password or matriculation number unknown."]},
        )

    signed_mat, _, _ = _signed_mat_for(student.mat_num)
    return _success_payload(student, signed_mat), 200
