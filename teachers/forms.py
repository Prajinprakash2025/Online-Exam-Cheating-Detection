from django import forms
from django.contrib.auth import get_user_model
from courses.models import Course
from .models import TeacherStudentAssignment

User = get_user_model()


class TeacherCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")

    class Meta:
        model = User
        fields = ['email', 'password', 'first_name', 'last_name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'form-control rounded-4 px-3 py-2 border-2',
                'placeholder': self.fields[field].label
            })

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user already exists with this email.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.is_teacher = True
        user.is_student = False
        user.is_staff = False
        # Use email prefix as username
        user.username = self._unique_username(self.cleaned_data['email'])
        if commit:
            user.save()
        return user

    def _unique_username(self, email):
        base = (email.split('@')[0] or 'teacher')[:140]
        username = base
        counter = 1
        while User.objects.filter(username__iexact=username).exists():
            suffix = f"-{counter}"
            username = f"{base[:150 - len(suffix)]}{suffix}"
            counter += 1
        return username


class TeacherStudentAssignmentForm(forms.ModelForm):
    teacher = forms.ModelChoiceField(queryset=User.objects.filter(is_teacher=True), label="Teacher")
    student = forms.ModelChoiceField(queryset=User.objects.filter(is_student=True, is_superuser=False), label="Student")
    course = forms.ModelChoiceField(queryset=Course.objects.all())

    class Meta:
        model = TeacherStudentAssignment
        fields = ['teacher', 'student', 'course']

class StudentCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    course = forms.ModelChoiceField(queryset=Course.objects.all(), required=False, label="Assign to Course")

    class Meta:
        model = User
        fields = ['email', 'password', 'first_name', 'last_name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'form-control rounded-4 px-3 py-2 border-2',
                'placeholder': self.fields[field].label
            })

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.is_teacher = False
        user.is_examiner = False
        user.is_student = True
        user.is_staff = False
        # To avoid verification steps for manually created students
        user.is_active = True
        # Use email prefix as username
        user.username = self.cleaned_data['email'].split('@')[0]
        if commit:
            user.save()
        return user
