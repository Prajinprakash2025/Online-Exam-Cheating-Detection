from django import forms
from django.contrib.auth import get_user_model
from courses.models import Course
from teachers.models import TeacherStudentAssignment
from .models import ExaminerTeacherAssignment

User = get_user_model()

class ExaminerSignupForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']

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
            raise forms.ValidationError("A conductor account already exists with this email.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        user.is_examiner = True
        user.is_student = False
        user.is_staff = False
        # Use email prefix as username
        user.username = self._unique_username(self.cleaned_data['email'])
        if commit:
            user.save()
        return user

    def _unique_username(self, email):
        base = (email.split('@')[0] or 'conductor')[:140]
        username = base
        counter = 1
        while User.objects.filter(username__iexact=username).exists():
            suffix = f"-{counter}"
            username = f"{base[:150 - len(suffix)]}{suffix}"
            counter += 1
        return username
class ExaminerStudentCreateForm(forms.ModelForm):
    conductor = forms.ModelChoiceField(queryset=User.objects.none(), label="Assign to Conductor")
    course = forms.ModelChoiceField(queryset=Course.objects.all(), label="Subject")

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']

    def __init__(self, *args, **kwargs):
        examiner = kwargs.pop('examiner', None)
        super().__init__(*args, **kwargs)
        if examiner:
            # Filter conductors managed by this examiner
            managed_teacher_ids = ExaminerTeacherAssignment.objects.filter(
                examiner=examiner
            ).values_list('teacher_id', flat=True)
            self.fields['conductor'].queryset = User.objects.filter(id__in=managed_teacher_ids)
            self.fields['course'].queryset = Course.objects.filter(created_by=examiner).order_by('-created_at')
        
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
        user.set_unusable_password()
        user.is_teacher = False
        user.is_examiner = False
        user.is_student = True
        user.is_staff = False
        user.is_active = True
        # Use email prefix as username
        user.username = self._unique_username(self.cleaned_data['email'])
        if commit:
            user.save()
            # Create assignment
            TeacherStudentAssignment.objects.create(
                teacher=self.cleaned_data['conductor'],
                student=user,
                course=self.cleaned_data['course']
            )
        return user

    def _unique_username(self, email):
        base = (email.split('@')[0] or 'candidate')[:140]
        username = base
        counter = 1
        while User.objects.filter(username__iexact=username).exists():
            suffix = f"-{counter}"
            username = f"{base[:150 - len(suffix)]}{suffix}"
            counter += 1
        return username

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
