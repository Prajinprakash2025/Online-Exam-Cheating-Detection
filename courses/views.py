import random
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages

from .models import Course, Video, User, Progress, Quiz, Enrollment
from .forms import CourseForm, VideoForm, QuizForm, StudentSignupForm

# ------------------------------------------------------------------
# ACCESS CONTROL HELPERS
# ------------------------------------------------------------------

def is_admin(user):
    return user.is_authenticated and (user.is_instructor or user.is_superuser)

# ------------------------------------------------------------------
# PUBLIC VIEWS
# ------------------------------------------------------------------

def home(request):
    courses = Course.objects.annotate(video_count=Count('videos')).all()
    return render(request, 'home.html', {'courses': courses})

from django.shortcuts import render
from django.db.models import Count, Q  # <--- CRITICAL: Import Q here

def course_list(request):
    # 1. Get the search term from the URL (e.g., ?q=python)
    query = request.GET.get('q')
    
    # 2. Start with the base query (All courses + video counts)
    courses = Course.objects.annotate(video_count=Count('videos'))

    # 3. Apply the filter if a query exists
    if query:
        courses = courses.filter(
            Q(title__icontains=query) |       # Search in Title
            Q(description__icontains=query)   # OR Search in Description
        )

    # 4. Pass the data (and the query) back to the template
    return render(request, 'courses.html', {
        'courses': courses, 
        'query': query 
    })

def mentors(request):
    return render(request, 'mentors.html')

def contact(request):
    if request.method == 'POST':
        return render(request, 'contact.html', {'success': True})
    return render(request, 'contact.html')

# ------------------------------------------------------------------
# AUTHENTICATION VIEWS
# ------------------------------------------------------------------

def signup_view(request):
    if request.method == 'POST':
        form = StudentSignupForm(request.POST)
        if form.is_valid():
            # 1. Save user but keep inactive
            user = form.save(commit=False)
            user.is_active = False 
            user.save()

            # 2. Generate and Save OTP
            otp = str(random.randint(100000, 999999))
            
            # 3. Save to Session (Temporary Storage)
            request.session['signup_otp'] = otp
            request.session['signup_user_id'] = user.id
            request.session['signup_email'] = user.email
            
            # 4. Send Email
            try:
                send_mail(
                    'Verify Your Account',
                    f'Your OTP is: {otp}',
                    settings.EMAIL_HOST_USER,
                    [user.email],
                    fail_silently=False,
                )
                print(f"DEBUG: Email sent to {user.email} with OTP {otp}")
                return redirect('verify_otp')
            except Exception as e:
                print(f"❌ Error sending email: {e}")
                user.delete() # Delete user so they can try again
                messages.error(request, "Email failed. Please try again.")
                return redirect('signup')
        else:
            # === DEBUG PRINT ===
            # This prints the specific error to your VS Code Terminal
            print("❌ FORM ERRORS:", form.errors)
    else:
        form = StudentSignupForm()
    return render(request, 'signup.html', {'form': form})


def verify_otp(request):
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        saved_otp = request.session.get('signup_otp')
        user_id = request.session.get('signup_user_id')

        # Robust comparison (convert both to string and strip spaces)
        if saved_otp and str(entered_otp).strip() == str(saved_otp).strip():
            try:
                user = User.objects.get(id=user_id)
                user.is_active = True
                user.save()
                
                # Log the user in
                login(request, user)
                
                # Cleanup session
                del request.session['signup_otp']
                del request.session['signup_user_id']
                del request.session['signup_email']
                
                messages.success(request, "Account Verified Successfully!")
                return redirect('home')
            except User.DoesNotExist:
                messages.error(request, "User not found. Please sign up again.")
                return redirect('signup')
        else:
            messages.error(request, "Invalid OTP. Please try again.")
            
    email = request.session.get('signup_email')
    return render(request, 'verify_otp.html', {'email': email})


# courses/views.py

def login_view(request):
    if request.method == 'POST':
        # 1. Get a copy of the POST data so we can modify it
        data = request.POST.copy()
        login_input = data.get('username') # This could be username OR email

        # 2. Check if the input looks like an email
        if login_input and '@' in login_input:
            try:
                # Try to find the user by email
                user = User.objects.get(email=login_input)
                # If found, replace the email with the actual username
                data['username'] = user.username
            except User.DoesNotExist:
                # If email doesn't exist, do nothing (let the form handle the error)
                pass

        # 3. Pass the (possibly modified) data to the form
        form = AuthenticationForm(data=data)
        
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if 'next' in request.POST:
                return redirect(request.POST.get('next'))
            return redirect('home')
    else:
        form = AuthenticationForm()
    
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('home')

# ------------------------------------------------------------------
# STUDENT FEATURES
# ------------------------------------------------------------------

@login_required
def profile_view(request):
    enrolled_courses = Enrollment.objects.filter(student=request.user)
    quiz_progress = Progress.objects.filter(student=request.user)
    
    context = {
        'enrolled_courses': enrolled_courses,
        'quiz_progress': quiz_progress,
    }
    return render(request, 'profile.html', context)

@login_required
def course_viewer(request, course_id, video_order):
    course = get_object_or_404(Course, id=course_id)
    video = get_object_or_404(Video, course=course, order=video_order)
    
    # Automatically enroll the student if they aren't already
    enrollment, created = Enrollment.objects.get_or_create(
        student=request.user, 
        course=course
    )

    # LOCKING LOGIC: Prevent skipping ahead
    if video_order > enrollment.current_lesson_index:
        return render(request, 'locked.html', {'course': course})

    all_videos = course.videos.all().order_by('order')
    
    # Check if this video has any quiz questions
    has_quiz = video.questions.exists()

    # --- NEW: Check if the student has passed this specific video ---
    # We check if a Progress record exists with passed=True
    is_passed = Progress.objects.filter(student=request.user, video=video, passed=True).exists()

    return render(request, 'video_player.html', {
        'course': course,
        'video': video,
        'all_videos': all_videos,
        'quiz': has_quiz, 
        'enrollment': enrollment,
        'is_passed': is_passed, # <--- Passing this is crucial for the PDF button
    })

@login_required
def take_quiz(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    questions = video.questions.all()
    enrollment = get_object_or_404(Enrollment, student=request.user, course=video.course)

    if request.method == 'POST':
        score = 0
        total_questions = questions.count()
        
        for q in questions:
            user_answer = request.POST.get(f'question_{q.id}')
            if user_answer and int(user_answer) == q.correct_option:
                score += 1
        
        if total_questions > 0:
            percentage = (score / total_questions) * 100
        else:
            percentage = 0

        # PASS CONDITION: 75%
        if percentage >= 75:
            Progress.objects.get_or_create(student=request.user, video=video, passed=True)
            
            # Unlock Next Video
            if video.order == enrollment.current_lesson_index:
                enrollment.current_lesson_index += 1
                enrollment.save()
            
            return render(request, 'quiz_result.html', {'status': 'passed', 'video': video, 'score': int(percentage)})
        else:
            return render(request, 'quiz_result.html', {'status': 'failed', 'video': video, 'score': int(percentage)})

    return render(request, 'take_quiz.html', {'questions': questions, 'video': video})

# ------------------------------------------------------------------
# INSTRUCTOR / ADMIN PANEL
# ------------------------------------------------------------------

@user_passes_test(is_admin)
def instructor_dashboard(request):
    students = User.objects.filter(is_student=True, is_superuser=False)
    total_students_count = students.count()
    
    courses = Course.objects.annotate(
        enrolled_count=Count('enrolled_students', distinct=True),
        video_count=Count('videos', distinct=True)
    )
    
    recent_activity = Progress.objects.select_related('student', 'video').order_by('-id')[:10]

    context = {
        'courses': courses,
        'total_students': total_students_count,
        'all_students': students,
        'recent_activity': recent_activity,
    }
    return render(request, 'dashboard.html', context)

@user_passes_test(is_admin)
def create_course(request):
    if request.method == 'POST':
        form = CourseForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('instructor_dashboard')
    else:
        form = CourseForm()
    return render(request, 'create_course.html', {'form': form})

@user_passes_test(is_admin)
def add_video(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    
    if request.method == 'POST':
        form = VideoForm(request.POST, request.FILES) 
        if form.is_valid():
            video = form.save(commit=False)
            video.course = course
            video.save()
            return redirect('instructor_dashboard')
    else:
        form = VideoForm()
        
    return render(request, 'add_video.html', {'form': form, 'course': course})

@user_passes_test(is_admin)
def add_quiz(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    
    if request.method == 'POST':
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.video = video
            quiz.save()
            
            if 'save_and_add' in request.POST:
                return redirect('add_quiz', video_id=video.id)
            else:
                return redirect('instructor_dashboard')
    else:
        form = QuizForm()
        
    return render(request, 'add_quiz.html', {'form': form, 'video': video})

@user_passes_test(is_admin)
def delete_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    video.delete()
    return redirect('instructor_dashboard')

@user_passes_test(is_admin)
def edit_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if request.method == 'POST':
        form = VideoForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            form.save()
            return redirect('instructor_dashboard')
    else:
        form = VideoForm(instance=video)
    return render(request, 'add_video.html', {'form': form, 'course': video.course, 'is_edit': True})

@user_passes_test(is_admin)
def delete_quiz(request, quiz_id):
    question = get_object_or_404(Quiz, id=quiz_id)
    video_id = question.video.id
    question.delete()
    return redirect('add_quiz', video_id=video_id)

@user_passes_test(is_admin)
def student_list(request):
    students = User.objects.filter(is_superuser=False).order_by('-date_joined')
    return render(request, 'student_list.html', {'students': students})

@user_passes_test(is_admin)
def student_detail(request, student_id):
    student = get_object_or_404(User, id=student_id)
    enrolled_courses = Enrollment.objects.filter(student=student)
    progress = Progress.objects.filter(student=student)
    return render(request, 'student_detail_admin.html', {
        'student': student,
        'enrolled_courses': enrolled_courses,
        'progress': progress
    })

@user_passes_test(is_admin)
def remove_student(request, student_id):
    # This is likely for removing a student from a course
    # Currently it deletes the user, make sure this is what you want
    student = get_object_or_404(User, id=student_id, is_superuser=False)
    student.delete()
    return redirect('instructor_dashboard')

@user_passes_test(is_admin)
def delete_student(request, student_id):
    student = get_object_or_404(User, id=student_id)
    if not student.is_superuser: 
        student.delete()
    return redirect('instructor_dashboard')

from django.utils import timezone # Add this import at the top

# courses/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse

# Make sure you have installed reportlab: pip install reportlab
from reportlab.pdfgen import canvas 

from .models import Course, Video, Enrollment, Progress

# --- 1. CERTIFICATE VIEW (PDF GENERATION) ---
# courses/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Course, Enrollment

@login_required
def certificate_view(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    enrollment = get_object_or_404(Enrollment, student=request.user, course=course)
    
    # Optional: Check if completed before showing
    if not enrollment.is_completed:
        messages.error(request, "You must complete the course to view the certificate.")
        return redirect('course_viewer', course_id=course.id, video_order=1)
        
    # Render the HTML template instead of sending a PDF file
    return render(request, 'certificate.html', {'course': course, 'enrollment': enrollment})

# --- 2. COMPLETE LESSON VIEW ---
@login_required
def complete_lesson(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    enrollment = get_object_or_404(Enrollment, student=request.user, course=video.course)

    # 1. Mark this specific video as passed
    Progress.objects.get_or_create(student=request.user, video=video, passed=True)

    # 2. Unlock Next Lesson (if currently at this lesson)
    if video.order == enrollment.current_lesson_index:
        enrollment.current_lesson_index += 1
        enrollment.save()

    # 3. CHECK COURSE COMPLETION
    total_videos = video.course.videos.count()
    # We count how many distinct videos the student has passed
    passed_videos = Progress.objects.filter(student=request.user, video__course=video.course, passed=True).count()

    # If they have passed ALL videos, mark course as complete
    if passed_videos >= total_videos and not enrollment.is_completed:
        enrollment.is_completed = True
        enrollment.completed_at = timezone.now()
        enrollment.save()
        messages.success(request, "Course Completed! Certificate Unlocked.")

    # 4. Redirect Logic
    next_order = video.order + 1
    next_video = Video.objects.filter(course=video.course, order=next_order).first()
    
    if next_video:
        return redirect('course_viewer', course_id=video.course.id, video_order=next_order)
    else:
        # If no next video, stay on current page (Certificate button will now appear)
        return redirect('course_viewer', course_id=video.course.id, video_order=video.order)
    

# courses/views.py
import random
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import User  # Make sure this matches your User model import

# 1. Ask for Email & Send Real OTP
def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        
        try:
            user = User.objects.get(email=email)
            
            # Generate 4-digit OTP
            otp = random.randint(1000, 9999)
            
            # Store OTP and Email in session (temporary memory)
            request.session['reset_otp'] = otp
            request.session['reset_email'] = email
            
            # --- SENDING THE REAL EMAIL ---
            subject = 'Your Password Reset OTP'
            message = f'Hello {user.first_name},\n\nYour OTP to reset your password is: {otp}\n\nValid for 10 minutes.'
            from_email = settings.EMAIL_HOST_USER
            recipient_list = [email]
            
            send_mail(subject, message, from_email, recipient_list, fail_silently=False)
            
            messages.success(request, f"OTP sent to {email}. Please check your inbox!")
            return redirect('enter_otp')
            
        except User.DoesNotExist:
            messages.error(request, "This email is not registered with us.")
        except Exception as e:
            messages.error(request, f"Error sending email: {str(e)}")
            
    return render(request, 'forgot_password.html')

# courses/views.py

def verify_otp_view(request):
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        session_otp = request.session.get('reset_otp')
        
        if str(entered_otp) == str(session_otp):
            messages.success(request, "OTP Verified! Set your new password.")
            return redirect('reset_new_password')
        else:
            messages.error(request, "Invalid OTP. Please try again.")
    
    # CHANGED: Use 'enter_otp.html' instead of 'verify_otp.html'
    return render(request, 'enter_otp.html')

# 3. Set New Password
def reset_new_password_view(request):
    # Security Check: Ensure user has passed OTP stage
    if not request.session.get('reset_email'):
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        email = request.session.get('reset_email')
        
        if new_password == confirm_password:
            try:
                user = User.objects.get(email=email)
                user.set_password(new_password) # Hashes the password securely
                user.save()
                
                # Cleanup: Remove sensitive data from session
                del request.session['reset_otp']
                del request.session['reset_email']
                
                messages.success(request, "Password changed successfully! Please login.")
                return redirect('login')
            except Exception as e:
                messages.error(request, "Something went wrong. Try again.")
        else:
            messages.error(request, "Passwords do not match.")
            
    return render(request, 'reset_new_password.html')

# courses/views.py
from django.contrib.auth.decorators import login_required


@login_required
def edit_profile_view(request):
    user = request.user
    
    if request.method == 'POST':
        # Get data from the form
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        
        # Update user object
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.save()
        
        messages.success(request, "Profile updated successfully!")
        return redirect('profile')
        
    return render(request, 'edit_profile.html')
# courses/views.py
from .models import Review
from .forms import ReviewForm

@login_required
def add_review(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            # Check if user already reviewed this course
            already_reviewed = Review.objects.filter(course=course, user=request.user).exists()
            
            if already_reviewed:
                messages.error(request, "You have already reviewed this course!")
            else:
                review = form.save(commit=False)
                review.course = course
                review.user = request.user
                review.save()
                messages.success(request, "Review added successfully!")
                
    # Redirect back to the course viewer (first lesson)
    return redirect('course_viewer', course_id=course.id, video_order=1)

# courses/views.py
from .models import Comment
from .forms import CommentForm

# courses/views.py

@login_required
def add_comment(request, video_id, parent_id=None): # Added parent_id=None
    video = get_object_or_404(Video, id=video_id)
    
    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.video = video
            comment.user = request.user
            
            # If this is a reply, link it to the parent comment
            if parent_id:
                parent_comment = get_object_or_404(Comment, id=parent_id)
                comment.parent = parent_comment
                
            comment.save()
            messages.success(request, "Response posted!")
            
    return redirect('course_viewer', course_id=video.course.id, video_order=video.order)