from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Course, Video, Quiz, User, Review, Comment

# ------------------------------------------------------------------
# INSTRUCTOR / ADMIN FORMS
# ------------------------------------------------------------------

# 1. Course Creation Form
class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['title', 'description', 'thumbnail']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control rounded-pill px-4', 'placeholder': 'Course Title'}),
            'description': forms.Textarea(attrs={'class': 'form-control rounded-4 px-4', 'rows': 4, 'placeholder': 'Course Description'}),
            'thumbnail': forms.FileInput(attrs={'class': 'form-control rounded-pill px-4'}),
        }

# 2. Video & Material Form
class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ['title', 'video_file', 'study_material', 'order']
        
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Video Title'}),
            'video_file': forms.FileInput(attrs={'class': 'form-control rounded-pill px-3 py-2'}),
            'order': forms.NumberInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Order (e.g. 1)'}),
            'study_material': forms.FileInput(attrs={'class': 'form-control rounded-pill px-3 py-2'}),
        }

# 3. Quiz Creation Form
class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['question', 'option_1', 'option_2', 'option_3', 'option_4', 'correct_option']
        widgets = {
            'question': forms.Textarea(attrs={'class': 'form-control rounded-4 px-4', 'rows': 3, 'placeholder': 'Enter the question'}),
            'option_1': forms.TextInput(attrs={'class': 'form-control rounded-pill px-4', 'placeholder': 'Option 1'}),
            'option_2': forms.TextInput(attrs={'class': 'form-control rounded-pill px-4', 'placeholder': 'Option 2'}),
            'option_3': forms.TextInput(attrs={'class': 'form-control rounded-pill px-4', 'placeholder': 'Option 3'}),
            'option_4': forms.TextInput(attrs={'class': 'form-control rounded-pill px-4', 'placeholder': 'Option 4'}),
            'correct_option': forms.NumberInput(attrs={'class': 'form-control rounded-pill px-4', 'placeholder': 'Enter correct option number (1-4)', 'min': 1, 'max': 4}),
        }

# ------------------------------------------------------------------
# STUDENT FORMS
# ------------------------------------------------------------------

class StudentSignupForm(UserCreationForm):
    # 1. Custom Fields with Styling
    email = forms.EmailField(
        required=True, 
        widget=forms.EmailInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Email Address'})
    )
    first_name = forms.CharField(
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Last Name'})
    )
    phone_number = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Phone Number'})
    )
    roll_no = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Roll No / Student ID'})
    )
    age = forms.IntegerField(
        required=False, 
        widget=forms.NumberInput(attrs={'class': 'form-control rounded-pill px-3', 'placeholder': 'Age'})
    )

    # 2. The Course Selection (ModelChoiceField)
    course_interest = forms.ModelChoiceField(
        queryset=Course.objects.all(),
        empty_label="Select a Course to Learn",
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select rounded-pill px-4 py-2', 
            'style': 'background-color: #f8f9fa; border: 1px solid #ced4da;'
        })
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('first_name', 'last_name', 'username', 'email', 'phone_number', 'age', 'roll_no', 'course_interest')

    # 3. Style the Password AND Username Fields
    def __init__(self, *args, **kwargs):
        super(StudentSignupForm, self).__init__(*args, **kwargs)
        
        # Style Password 1
        if 'password1' in self.fields:
            self.fields['password1'].widget.attrs.update({
                'class': 'form-control rounded-pill px-4 py-2', 
                'placeholder': 'Password'
            })
        
        # Style Password 2
        if 'password2' in self.fields:
            self.fields['password2'].widget.attrs.update({
                'class': 'form-control rounded-pill px-4 py-2', 
                'placeholder': 'Confirm Password'
            })

        # Style Username
        if 'username' in self.fields:
            self.fields['username'].widget.attrs.update({
                'class': 'form-control rounded-pill px-4 py-2', 
                'placeholder': 'Choose a Username'
            })

# ------------------------------------------------------------------
# INTERACTION FORMS
# ------------------------------------------------------------------

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'comment']
        widgets = {
            'rating': forms.Select(attrs={'class': 'form-select rounded-pill px-3'}),
            'comment': forms.Textarea(attrs={
                'class': 'form-control rounded-4 px-3 py-2', 
                'rows': 3, 
                'placeholder': 'Write your review here...'
            }),
        }

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['text']
        widgets = {
            'text': forms.Textarea(attrs={
                'class': 'form-control rounded-4 px-3 py-2', 
                'rows': 3, 
                'placeholder': 'Ask a question or share your thoughts...'
            }),
        }