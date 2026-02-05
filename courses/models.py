from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator


# courses/models.py

class User(AbstractUser):
    is_instructor = models.BooleanField(default=False)
    is_student = models.BooleanField(default=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    
    # NEW FIELDS ADDED HERE
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    age = models.PositiveIntegerField(blank=True, null=True)
    roll_no = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Your Student ID")
    course_interest = models.ForeignKey('Course', on_delete=models.SET_NULL, null=True, blank=True, related_name='interested_students')  

    def __str__(self):
        return self.username

# CONTENT MODELS
class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

# models.py
# courses/models.py
from django.db import models
from django.core.validators import FileExtensionValidator  # Important for checking file types

class Video(models.Model):
    # Use string 'Course' to avoid circular import errors
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=200)
    
    # CHANGED: Replaced 'youtube_url' with 'video_file'
    video_file = models.FileField(
        upload_to='course_videos/',
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'avi', 'mkv'])],
        help_text="Upload a video file (mp4, mov, avi, mkv)"
    )
    
    order = models.PositiveIntegerField(help_text="Lesson order: 1, 2, 3...")

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.order}. {self.title}"

class Quiz(models.Model):
    # CHANGE THIS LINE: from OneToOneField to ForeignKey
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='questions')
    
    question = models.TextField()
    option_1 = models.CharField(max_length=200)
    option_2 = models.CharField(max_length=200)
    option_3 = models.CharField(max_length=200)
    option_4 = models.CharField(max_length=200)
    correct_option = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])

    def __str__(self):
        return f"Question: {self.question[:50]}"
import uuid # <--- Add this at the very top of models.py

# ... your other models ...

class Enrollment(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrolled_students')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    current_lesson_index = models.PositiveIntegerField(default=1) 
    
    # === NEW FIELDS FOR CERTIFICATE ===
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    certificate_id = models.CharField(max_length=50, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.is_completed and not self.certificate_id:
            # Generate a unique certificate ID (e.g., CERT-1234abcd)
            self.certificate_id = f"CERT-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('student', 'course')


class Progress(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    video = models.ForeignKey(Video, on_delete=models.CASCADE)
    passed = models.BooleanField(default=False)