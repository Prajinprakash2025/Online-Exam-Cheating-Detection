from django import forms
from django.contrib.auth import get_user_model
from courses.models import Course
from teachers.models import TeacherStudentAssignment
from .models import ExaminerTeacherAssignment

User = get_user_model()

class ExaminerSignupForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'form-control rounded-4 px-3 py-2 border-2',
                'placeholder': self.fields[field].label
            })

    def clean(self):
        cleaned_data = super().clean()
        pwd = cleaned_data.get("password")
        cpwd = cleaned_data.get("confirm_password")
        if pwd and cpwd and pwd != cpwd:
            self.add_error('confirm_password', "Passwords do not match!")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.is_examiner = True
        user.is_student = False
        user.is_staff = False
        # Use email prefix as username
        user.username = self.cleaned_data['email'].split('@')[0]
        if commit:
            user.save()
        return user
class ExaminerStudentCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    conductor = forms.ModelChoiceField(queryset=User.objects.none(), label="Assign to Conductor")
    course = forms.ModelChoiceField(queryset=Course.objects.all(), label="Exam Subject")

    class Meta:
        model = User
        fields = ['email', 'password', 'first_name', 'last_name']

    def __init__(self, *args, **kwargs):
        examiner = kwargs.pop('examiner', None)
        super().__init__(*args, **kwargs)
        if examiner:
            # Filter conductors managed by this examiner
            managed_teacher_ids = ExaminerTeacherAssignment.objects.filter(
                examiner=examiner
            ).values_list('teacher_id', flat=True)
            self.fields['conductor'].queryset = User.objects.filter(id__in=managed_teacher_ids)
        
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
        user.is_active = True
        # Use email prefix as username
        user.username = self.cleaned_data['email'].split('@')[0]
        if commit:
            user.save()
            # Create assignment
            TeacherStudentAssignment.objects.create(
                teacher=self.cleaned_data['conductor'],
                student=user,
                course=self.cleaned_data['course']
            )
        return user

class SubjectForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['title', 'description', 'thumbnail']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'form-control rounded-4 px-3 py-2 border-2',
                'placeholder': self.fields[field].label
            })
