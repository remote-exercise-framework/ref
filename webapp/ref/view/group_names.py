from flask import abort, current_app, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from wtforms import (
    BooleanField,
    Form,
    StringField,
    SubmitField,
    TextAreaField,
    validators,
)

from ref import refbp
from ref.core import admin_required, flash
from ref.core.util import on_integrity_error, redirect_to_next
from ref.model import GroupNameList, SystemSettingsManager, UserGroup


class GroupNameListForm(Form):
    name = StringField("List name", validators=[validators.DataRequired()])
    enabled_for_registration = BooleanField(
        "Offer this list as a source for group names during student registration."
    )
    names = TextAreaField(
        "Names (one per line)", validators=[validators.DataRequired()]
    )
    submit = SubmitField("Save")


def _parse_names(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


@refbp.route("/admin/system/group-names/", methods=("GET",))
@admin_required
def group_names_view_all():
    lists = GroupNameList.query.order_by(GroupNameList.id).all()
    return render_template(
        "system_group_names.html",
        lists=lists,
        groups_enabled=SystemSettingsManager.GROUPS_ENABLED.value,
    )


@refbp.route("/admin/system/group-names/new/", methods=("GET", "POST"))
@admin_required
def group_names_create():
    form = GroupNameListForm(request.form)
    if form.submit.data and form.validate():
        lst = GroupNameList()
        lst.name = form.name.data
        lst.enabled_for_registration = bool(form.enabled_for_registration.data)
        lst.names = _parse_names(form.names.data)
        try:
            current_app.db.session.add(lst)
            current_app.db.session.commit()
        except IntegrityError:
            on_integrity_error()
            return render_template("system_group_names_edit.html", form=form, lst=None)
        flash.success(f"Group name list '{lst.name}' created")
        return redirect(url_for("ref.group_names_view_all"))
    return render_template("system_group_names_edit.html", form=form, lst=None)


@refbp.route("/admin/system/group-names/<int:list_id>/edit/", methods=("GET", "POST"))
@admin_required
def group_names_edit(list_id):
    lst = GroupNameList.query.filter(GroupNameList.id == list_id).one_or_none()
    if not lst:
        flash.error(f"Unknown group name list ID {list_id}")
        abort(400)

    form = GroupNameListForm(request.form)
    if form.submit.data and form.validate():
        lst.name = form.name.data
        lst.enabled_for_registration = bool(form.enabled_for_registration.data)
        lst.names = _parse_names(form.names.data)
        try:
            current_app.db.session.commit()
        except IntegrityError:
            on_integrity_error()
            return render_template("system_group_names_edit.html", form=form, lst=lst)
        flash.success(f"Group name list '{lst.name}' updated")
        return redirect(url_for("ref.group_names_view_all"))

    if not form.submit.data:
        form.name.data = lst.name
        form.enabled_for_registration.data = lst.enabled_for_registration
        form.names.data = "\n".join(lst.names or [])
    return render_template("system_group_names_edit.html", form=form, lst=lst)


@refbp.route("/admin/system/group-names/<int:list_id>/delete/", methods=("GET", "POST"))
@admin_required
def group_names_delete(list_id):
    lst = GroupNameList.query.filter(GroupNameList.id == list_id).one_or_none()
    if not lst:
        flash.error(f"Unknown group name list ID {list_id}")
        abort(400)

    groups_using = UserGroup.query.filter(UserGroup.source_list_id == lst.id).count()
    if groups_using:
        flash.error(
            f"Unable to delete '{lst.name}': {groups_using} existing groups were created from it"
        )
        return redirect_to_next()

    try:
        current_app.db.session.delete(lst)
        current_app.db.session.commit()
    except IntegrityError:
        on_integrity_error()
    else:
        flash.info(f"Group name list '{lst.name}' deleted")
    return redirect_to_next()
