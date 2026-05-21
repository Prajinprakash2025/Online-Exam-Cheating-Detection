import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.conf import settings
from django.utils import timezone

# ------------------------------------------------------------------
# USER MODEL
# ------------------------------------------------------------------
class User(AbstractUser):
    email = models.EmailField(unique=True)
    
    is_instructor = models.BooleanField(default=False)
    is_teacher = models.BooleanField(default=False)
    is_examiner = models.BooleanField(default=False)
    is_student = models.BooleanField(default=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']
    
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    age = models.PositiveIntegerField(blank=True, null=True)
    roll_no = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Your Student ID")
    
    # Professional fields for Exam Conductors
    bio = models.TextField(blank=True, null=True, help_text="Short biography or professional summary")
    specialty = models.CharField(max_length=100, blank=True, null=True, help_text="Expertise (e.g. Mathematics, AI, Math)")
    experience_years = models.PositiveIntegerField(default=0)

    course_interest = models.ForeignKey('Course', on_delete=models.SET_NULL, null=True, blank=True, related_name='interested_students')  

    def __str__(self):
        return self.username


# ------------------------------------------------------------------
# CONTENT MODELS
# ------------------------------------------------------------------
class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Video(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=200)
    
    video_file = models.FileField(
        upload_to='course_videos/',
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'avi', 'mkv'])],
        help_text="Upload a video file (mp4, mov, avi, mkv)"
    )
    
    study_material = models.FileField(
        upload_to='materials/', 
        blank=True, 
        null=True,
        help_text="Upload PDF notes for students"
    )
    
    order = models.PositiveIntegerField(help_text="Lesson order: 1, 2, 3...")

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.order}. {self.title}"


# ------------------------------------------------------------------
# QUIZ & INTERACTION MODELS
# ------------------------------------------------------------------
class Quiz(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='questions')
    
    question = models.TextField()
    option_1 = models.CharField(max_length=200)
    option_2 = models.CharField(max_length=200)
    option_3 = models.CharField(max_length=200)
    option_4 = models.CharField(max_length=200)
    correct_option = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])

    def __str__(self):
        return f"Question: {self.question[:50]}"

class Exam(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='exams')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    passing_score = models.FloatField(default=75.0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_exams')

    def __str__(self):
        return f"{self.title} ({self.course.title})"

class ExamQuestion(models.Model):
    QUESTION_TYPES = (
        ('mcq', 'Single Choice'),
        ('multi', 'Multiple Choice'),
        ('essay', 'Descriptive Essay'),
    )
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    q_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='mcq')
    question = models.TextField()
    
    # Options (Used for MCQ and Multi)
    option_1 = models.CharField(max_length=200, blank=True, null=True)
    option_2 = models.CharField(max_length=200, blank=True, null=True)
    option_3 = models.CharField(max_length=200, blank=True, null=True)
    option_4 = models.CharField(max_length=200, blank=True, null=True)
    
    # For MCQ: single digit (1-4). For Multi: comma-separated (e.g. "1,3")
    correct_answer = models.CharField(max_length=50, blank=True, null=True)
    
    points = models.FloatField(default=1.0)

    def __str__(self):
        return f"[{self.get_q_type_display()}] {self.question[:50]}"

class Review(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)]) 
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.course.title} ({self.rating} stars)"
    
class Comment(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.video.title}"


# ------------------------------------------------------------------
# TRACKING & ENROLLMENT MODELS
# ------------------------------------------------------------------
class Enrollment(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrolled_students')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    current_lesson_index = models.PositiveIntegerField(default=1) 
    
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    certificate_id = models.CharField(max_length=50, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.is_completed and not self.certificate_id:
            self.certificate_id = f"CERT-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('student', 'course')

class CourseAccessRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_access_requests')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='access_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_course_requests')

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.student} requested {self.course} ({self.status})"

class Progress(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    video = models.ForeignKey(Video, on_delete=models.CASCADE)
    passed = models.BooleanField(default=False)


# ------------------------------------------------------------------
# AI PROCTORING & QUIZ SESSION MODELS
# ------------------------------------------------------------------
class QuizSession(models.Model):
    """
    Tracks a student's active proctored attempt at a Video's Quiz. 
    """
    STATUS_CHOICES = (
        ('ongoing', 'Ongoing'),
        ('submitted', 'Submitted'),
        ('flagged', 'Flagged for Review'),
        ('disqualified', 'Disqualified'),
    )

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_sessions')
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='proctored_sessions', null=True, blank=True)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='proctored_sessions', null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ongoing')
    
    is_reviewed = models.BooleanField(default=False)
    admin_notes = models.TextField(blank=True, null=True)
    allow_retake = models.BooleanField(default=False)  # Instructor can toggle after a failed attempt

    def __str__(self):
        title = self.video.title if self.video else (self.exam.title if self.exam else "Unknown")
        return f"{self.student.username} - {title} ({self.status})"

class ExamAssignment(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='assignments')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=(
        ('assigned', 'Assigned'),
        ('submitted', 'Submitted'),
        ('completed', 'Completed'),
    ), default='assigned')
    
    final_score = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ('exam', 'student')

    def __str__(self):
        return f"{self.student.username} assigned to {self.exam.title}"

class StudentAnswer(models.Model):
    session = models.ForeignKey(QuizSession, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(ExamQuestion, on_delete=models.CASCADE)
    
    # For MCQ/Multi: list of indices "1,2"
    selected_options = models.CharField(max_length=50, blank=True, null=True)
    # For Essay
    essay_text = models.TextField(blank=True, null=True)
    
    is_correct = models.BooleanField(null=True, blank=True)
    marks_earned = models.FloatField(default=0.0)

    def __str__(self):
        return f"Answer by {self.session.student.username} to {self.question.id}"

class ProctoringLog(models.Model):
    """
    Stores the output from the Behaviour Analysis Engine (OpenCV/MediaPipe).
    """
    VIOLATION_TYPES = (
        ('no_face', 'Face Absence'),
        ('multi_face', 'Multiple Persons Detected'),
        ('gaze_deviation', 'Eye Gaze Deviation'),
        ('head_pose', 'Suspicious Head Movement'),
        ('tab_switch', 'Browser Tab Switch'),
        ('phone_detected', 'Mobile Phone Detected'),
    )

    session = models.ForeignKey(QuizSession, on_delete=models.CASCADE, related_name='proctoring_logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    violation_type = models.CharField(max_length=30, choices=VIOLATION_TYPES)
    
    confidence_score = models.FloatField(null=True, blank=True)
    evidence_image = models.ImageField(upload_to='proctoring_evidence/', blank=True, null=True)

    def __str__(self):
        return f"{self.get_violation_type_display()} at {self.timestamp.strftime('%H:%M:%S')}"
