from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, PasswordField, BooleanField, SelectField, ValidationError
from wtforms.validators import DataRequired, Email, Length, EqualTo


class LoginForm(FlaskForm):
    email = StringField("Email Address", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=256)])
    remember_me = BooleanField("Remember Me")


class UpdateAccount(FlaskForm):
    current_pass = PasswordField("Current Password", validators=[DataRequired(), Length(min=8, max=256)])
    new_pass = PasswordField(
        "New Password",
        validators=[DataRequired(), EqualTo("new_pass_verify", message="Passwords must match"), Length(min=8, max=256)],
    )
    new_pass_verify = PasswordField("Verify Password", validators=[DataRequired(), Length(min=8, max=256)])

    def __init__(self, user, *args, **kwargs):
        super(UpdateAccount, self).__init__(*args, **kwargs)
        self.user = user

    def validate_current_pass(self, field):
        if not self.user.check_password(field.data):
            raise ValidationError("Current password incorrect")


class CreateAppForm(FlaskForm):
    title = StringField("Project Name", validators=[DataRequired()])
    project_type = SelectField(
        "Project Type",
        validators=[DataRequired()],
        choices=[("simple", "Simple"), ("versioned", "Versioned")],
    )


class UploadMinidumpForm(FlaskForm):
    minidump = FileField(
        "Select Minidump file",
        validators=[FileRequired(), FileAllowed(["dmp"], "Minidump Files Only")],
    )
    project = SelectField(u"Projects", coerce=str, validate_choice=False)

    def add_project_choice(self, value, title):
        data = (value, title)
        if not self.project.choices:
            self.project.choices = [data]
        else:
            self.project.choices.append(data)
