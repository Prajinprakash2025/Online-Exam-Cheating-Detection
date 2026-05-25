import json
import base64
import cv2
import numpy as np
import random
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q
from django.contrib.auth import login, logout
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.core.files.base import ContentFile

from .models import Course, Video, User, Progress, Quiz, Enrollment, Review, Comment, QuizSession, ProctoringLog, CourseAccessRequest
from .forms import CourseForm, VideoForm, QuizForm, StudentSignupForm, ReviewForm, CommentForm
from .proctoring import calculate_risk_report

# ------------------------------------------------------------------
# ACCESS CONTROL HELPERS
# ------------------------------------------------------------------
def is_admin(user):
    return user.is_authenticated and (user.is_instructor or user.is_superuser)

# ------------------------------------------------------------------
# PUBLIC VIEWS
# ------------------------------------------------------------------
def home(request):
    # Fetch Examiners and Teachers for the landing page directory
    conductors = User.objects.filter(Q(is_examiner=True) | Q(is_teacher=True)).exclude(is_superuser=True).order_by('?')[:8]
    # Fetch all subjects/courses to display on the landing page
    courses = Course.objects.annotate(video_count=Count('videos')).order_by('-created_at')
    course_list_items = list(courses)
    enrolled_course_ids = set()
    access_requests_by_course = {}

    if request.user.is_authenticated:
        enrolled_course_ids = set(Enrollment.objects.filter(
            student=request.user
        ).values_list('course_id', flat=True))
        access_requests_by_course = {
            item.course_id: item for item in CourseAccessRequest.objects.filter(student=request.user)
        }

    for course in course_list_items:
        course.is_enrolled = course.id in enrolled_course_ids
        course.access_request = access_requests_by_course.get(course.id)

    context = {
        'conductors': conductors,
        'courses': course_list_items,
    }

    if request.user.is_authenticated:
        from teachers.models import TeacherStudentAssignment
        from examiners.models import ExaminerTeacherAssignment
        from .models import Exam, ExamAssignment

        if request.user.is_examiner:
            teacher_ids = ExaminerTeacherAssignment.objects.filter(
                examiner=request.user
            ).values_list('teacher_id', flat=True)
            context.update({
                'managed_teachers_count': len(set(teacher_ids)),
                'managed_candidates_count': TeacherStudentAssignment.objects.filter(
                    teacher_id__in=teacher_ids
                ).values_list('student_id', flat=True).distinct().count(),
                'managed_exam_count': Exam.objects.filter(created_by=request.user).count(),
            })
        elif request.user.is_teacher:
            assignments = TeacherStudentAssignment.objects.filter(teacher=request.user)
            context.update({
                'teacher_students_count': assignments.values_list('student_id', flat=True).distinct().count(),
                'teacher_subjects_count': assignments.values_list('course_id', flat=True).distinct().count(),
                'teacher_exam_count': Exam.objects.filter(created_by=request.user).count(),
                'teacher_review_count': QuizSession.objects.filter(
                    student_id__in=assignments.values_list('student_id', flat=True)
                ).exclude(status='ongoing').filter(is_reviewed=False).count(),
            })
        else:
            context.update({
                'student_assigned_count': ExamAssignment.objects.filter(student=request.user).count(),
                'student_pending_count': ExamAssignment.objects.filter(student=request.user, status='submitted').count(),
                'student_published_count': ExamAssignment.objects.filter(student=request.user, status='completed').count(),
            })

    return render(request, 'home.html', context)

def about(request):
    return render(request, 'about.html')

def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def faq(request):
    return render(request, 'faq.html')

def course_list(request):
    query = request.GET.get('q')
    courses = Course.objects.annotate(video_count=Count('videos'))

    if query:
        courses = courses.filter(
            Q(title__icontains=query) | 
            Q(description__icontains=query) 
        )

    course_list_items = list(courses)
    enrolled_course_ids = set()
    access_requests_by_course = {}

    if request.user.is_authenticated:
        enrolled_course_ids = set(Enrollment.objects.filter(
            student=request.user
        ).values_list('course_id', flat=True))
        access_requests_by_course = {
            item.course_id: item for item in CourseAccessRequest.objects.filter(student=request.user)
        }

    for course in course_list_items:
        course.is_enrolled = course.id in enrolled_course_ids
        course.access_request = access_requests_by_course.get(course.id)

    return render(request, 'courses.html', {
        'courses': course_list_items,
        'query': query 
    })


@login_required
def request_course_access(request, course_id):
    course = get_object_or_404(Course, id=course_id)

    if not request.user.is_student:
        messages.error(request, "Only student accounts can enroll in courses.")
        return redirect('course_list')

    enrollment, created = Enrollment.objects.get_or_create(student=request.user, course=course)
    
    CourseAccessRequest.objects.update_or_create(
        student=request.user,
        course=course,
        defaults={'status': 'approved', 'reviewed_at': timezone.now()}
    )

    messages.success(request, f"Successfully enrolled in '{course.title}'! You can start learning now.")
    return redirect('course_viewer', course_id=course.id, video_order=1)


@login_required
def course_checkout(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    
    if not request.user.is_student:
        messages.error(request, "Only student accounts can purchase courses.")
        return redirect('course_list')
        
    if Enrollment.objects.filter(student=request.user, course=course).exists():
        messages.info(request, "You are already enrolled in this course.")
        return redirect('course_viewer', course_id=course.id, video_order=1)
        
    if request.method == 'POST':
        import uuid
        from courses.models import Payment
        
        payment = Payment.objects.create(
            student=request.user,
            course=course,
            amount=course.price,
            transaction_id=f"TXN-{uuid.uuid4().hex[:12].upper()}",
            status='completed'
        )
        
        Enrollment.objects.get_or_create(student=request.user, course=course)
        
        CourseAccessRequest.objects.update_or_create(
            student=request.user,
            course=course,
            defaults={'status': 'approved', 'reviewed_at': timezone.now()}
        )
        
        try:
            from courses.utils import generate_revenue_chart
            generate_revenue_chart()
        except Exception as e:
            print(f"Error regenerating chart: {e}")
            
        messages.success(request, f"Mock payment of ₹{course.price} successful! '{course.title}' unlocked.")
        return redirect('course_viewer', course_id=course.id, video_order=1)
        
    return render(request, 'checkout.html', {'course': course})


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
    # Student self-signup is disabled per new "Exam Portal" logic.
    # Redirect to a page explaining that access is granted by Teachers/Examiners.
    return render(request, 'restricted_signup.html')


STUDENT_LOGIN_OTP_MINUTES = 10


def _clear_student_login_otp(request):
    for key in (
        'student_login_user_id',
        'student_login_email',
        'student_login_otp',
        'student_login_otp_expires_at',
        'student_login_next',
    ):
        request.session.pop(key, None)


def _print_student_login_otp(email, otp):
    print("\n" + "=" * 64)
    print(f"ExamGate student login OTP for {email}: {otp}")
    print("=" * 64 + "\n")


def _send_student_login_otp(email, otp, user):
    _print_student_login_otp(email, otp)

    subject = 'Your ExamGate Student Login OTP'
    message = (
        f"Hello {user.first_name or user.username},\n\n"
        f"Your ExamGate student login OTP is: {otp}\n\n"
        f"This code is valid for {STUDENT_LOGIN_OTP_MINUTES} minutes."
    )
    from_email = settings.DEFAULT_FROM_EMAIL

    if not from_email:
        return

    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
    except Exception as exc:
        if not settings.DEBUG:
            raise
        print(f"Student login OTP email delivery skipped in DEBUG after error: {exc}")


def _student_login_context(request):
    expires_at = request.session.get('student_login_otp_expires_at')
    otp_email = request.session.get('student_login_email')
    next_url = request.session.get('student_login_next') or ''
    is_admin_login = next_url == '/dashboard/' or next_url == 'instructor_dashboard'

    if not expires_at or not otp_email:
        return {'otp_sent': False, 'is_admin_login': is_admin_login}

    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        _clear_student_login_otp(request)
        return {'otp_sent': False}

    if timezone.now().timestamp() > expires_at:
        _clear_student_login_otp(request)
        return {'otp_sent': False}

    return {'otp_sent': True, 'otp_email': otp_email, 'is_admin_login': is_admin_login}

def verify_otp(request):
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        saved_otp = request.session.get('signup_otp')
        user_id = request.session.get('signup_user_id')

        if saved_otp and str(entered_otp).strip() == str(saved_otp).strip():
            try:
                user = User.objects.get(id=user_id)
                user.is_active = True
                user.save()
                login(request, user)
                
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

def login_view(request):
    if request.GET.get('reset') == '1':
        _clear_student_login_otp(request)
        return redirect('login')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'verify_login_otp':
            entered_otp = (request.POST.get('otp') or '').strip()
            saved_otp = str(request.session.get('student_login_otp') or '')
            user_id = request.session.get('student_login_user_id')
            expires_at = request.session.get('student_login_otp_expires_at')

            if not user_id or not saved_otp or not expires_at:
                messages.error(request, "Please request a fresh login OTP.")
                return redirect('login')

            try:
                expires_at = float(expires_at)
            except (TypeError, ValueError):
                _clear_student_login_otp(request)
                messages.error(request, "Please request a fresh login OTP.")
                return redirect('login')

            if timezone.now().timestamp() > expires_at:
                _clear_student_login_otp(request)
                messages.error(request, "Your login OTP expired. Please request a new one.")
                return redirect('login')

            if entered_otp != saved_otp:
                messages.error(request, "Invalid OTP. Please try again.")
                context = _student_login_context(request)
                context['next'] = request.session.get('student_login_next', '')
                return render(request, 'login.html', context)

            user = get_object_or_404(User, id=user_id, is_active=True)
            next_url = request.session.get('student_login_next') or 'home'
            login(request, user)
            _clear_student_login_otp(request)
            if next_url == 'home' and (user.is_instructor or user.is_superuser):
                return redirect('instructor_dashboard')
            return redirect(next_url)

        email = (request.POST.get('email') or '').strip().lower()
        next_url = request.POST.get('next') or request.GET.get('next') or ''
        is_admin_login = next_url == '/dashboard/' or next_url == 'instructor_dashboard'

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if is_admin_login:
            allowed_user = user and (user.is_instructor or user.is_superuser)
            error_message = "No active admin account was found for that email."
        else:
            allowed_user = user and (user.is_student or user.is_instructor or user.is_superuser)
            error_message = "No active portal account was found for that email."

        if not allowed_user:
            messages.error(request, error_message)
            return render(request, 'login.html', {
                'otp_sent': False,
                'next': next_url,
                'email_value': email,
                'is_admin_login': is_admin_login,
            })

        otp = f"{random.randint(100000, 999999)}"
        _send_student_login_otp(user.email, otp, user)

        request.session['student_login_user_id'] = user.id
        request.session['student_login_email'] = user.email
        request.session['student_login_otp'] = otp
        request.session['student_login_otp_expires_at'] = (
            timezone.now() + timedelta(minutes=STUDENT_LOGIN_OTP_MINUTES)
        ).timestamp()
        request.session['student_login_next'] = next_url or 'home'

        messages.success(request, f"OTP generated for {user.email}. Check your terminal for the code.")
        context = _student_login_context(request)
        context['next'] = next_url
        context['is_admin_login'] = is_admin_login
        return render(request, 'login.html', context)

    context = _student_login_context(request)
    context['next'] = request.GET.get('next', '')
    context['is_admin_login'] = context['next'] == '/dashboard/' or context['next'] == 'instructor_dashboard'
    return render(request, 'login.html', context)

def logout_view(request):
    logout(request)
    return redirect('home')

def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            otp = random.randint(1000, 9999)
            
            request.session['reset_otp'] = otp
            request.session['reset_email'] = email
            
            subject = 'Your Password Reset OTP'
            message = f'Hello {user.first_name},\n\nYour OTP to reset your password is: {otp}\n\nValid for 10 minutes.'
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email]
            
            send_mail(subject, message, from_email, recipient_list, fail_silently=False)
            
            messages.success(request, f"OTP sent to {email}. Please check your inbox!")
            return redirect('enter_otp')
            
        except User.DoesNotExist:
            messages.error(request, "This email is not registered with us.")
        except Exception as e:
            messages.error(request, f"Error sending email: {str(e)}")
            
    return render(request, 'forgot_password.html')

def verify_otp_view(request):
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        session_otp = request.session.get('reset_otp')
        
        if str(entered_otp) == str(session_otp):
            messages.success(request, "OTP Verified! Set your new password.")
            return redirect('reset_new_password')
        else:
            messages.error(request, "Invalid OTP. Please try again.")
    
    return render(request, 'enter_otp.html')

def reset_new_password_view(request):
    if not request.session.get('reset_email'):
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        email = request.session.get('reset_email')
        
        if new_password == confirm_password:
            try:
                user = User.objects.get(email=email)
                user.set_password(new_password)
                user.save()
                
                del request.session['reset_otp']
                del request.session['reset_email']
                
                messages.success(request, "Password changed successfully! Please login.")
                return redirect('login')
            except Exception as e:
                messages.error(request, "Something went wrong. Try again.")
        else:
            messages.error(request, "Passwords do not match.")
            
    return render(request, 'reset_new_password.html')

# ------------------------------------------------------------------
# STUDENT FEATURES
# ------------------------------------------------------------------
@login_required
def profile_view(request):
    from courses.models import ExamAssignment
    enrolled_courses = Enrollment.objects.filter(student=request.user)
    quiz_progress = Progress.objects.filter(student=request.user)
    exam_assignments = ExamAssignment.objects.filter(student=request.user).select_related('exam', 'exam__course')
    
    context = {
        'enrolled_courses': enrolled_courses,
        'quiz_progress': quiz_progress,
        'exam_assignments': exam_assignments,
    }
    return render(request, 'profile.html', context)

@login_required
def edit_profile_view(request):
    user = request.user
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        user.email = request.POST.get('email')
        user.save()
        messages.success(request, "Profile updated successfully!")
        return redirect('profile')
        
    return render(request, 'edit_profile.html')

@login_required
def course_viewer(request, course_id, video_order):
    course = get_object_or_404(Course, id=course_id)
    
    enrollment = Enrollment.objects.filter(student=request.user, course=course).first()
    if not enrollment:
        messages.error(request, "Please enroll in or purchase this course first to start learning.")
        return redirect('course_list')

    all_videos = course.videos.all().order_by('order')
    if not all_videos.exists():
        return render(request, 'empty_course.html', {'course': course})

    first_video = all_videos.first()
    
    # Self-heal lock condition: if enrollment.current_lesson_index is less than the first video's order,
    # update it to the first video's order so the student is not locked out of the start of the course.
    if enrollment.current_lesson_index < first_video.order:
        enrollment.current_lesson_index = first_video.order
        enrollment.save(update_fields=['current_lesson_index'])

    # Self-heal video matching: fallback to the first video if the requested video_order is not found
    video = Video.objects.filter(course=course, order=video_order).first()
    if not video:
        return redirect('course_viewer', course_id=course.id, video_order=first_video.order)
    
    if video_order > enrollment.current_lesson_index:
        return render(request, 'locked.html', {'course': course})

    has_quiz = video.questions.exists()
    is_passed = Progress.objects.filter(student=request.user, video=video, passed=True).exists()

    return render(request, 'video_player.html', {
        'course': course,
        'video': video,
        'all_videos': all_videos,
        'quiz': has_quiz, 
        'enrollment': enrollment,
        'is_passed': is_passed, 
    })


# ==================================================================
# 🚀 PROCTORED QUIZ LOGIC (MERGED EXAM & QUIZ)
# ==================================================================
@login_required
def take_quiz(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    questions = video.questions.all()
    enrollment = get_object_or_404(Enrollment, student=request.user, course=video.course)

    # 1. SETUP PROCTORING SESSION
    session, created = QuizSession.objects.get_or_create(
        student=request.user,
        video=video,
        defaults={'status': 'ongoing'}
    )
    
    if request.method == 'POST' and request.POST.get('action') == 'start_assessment':
        session.end_time = timezone.now() + timedelta(minutes=15)
        session.status = 'ongoing'
        session.save(update_fields=['end_time', 'status'])
        request.session[f'assessment_started_{session.id}'] = True
        return redirect('take_quiz', video_id=video.id)

    if session.status == 'ongoing' and session.end_time and not request.session.get(f'assessment_started_{session.id}'):
        session.end_time = None
        session.save(update_fields=['end_time'])

    exam_not_started = not session.end_time
    if exam_not_started:
        return render(request, 'take_quiz.html', {
            'questions': questions,
            'video': video,
            'session': session,
            'remaining_time': 15 * 60,
            'exam_not_started': True,
        })

    remaining_time = (session.end_time - timezone.now()).total_seconds()

    # 3. GRADING & SUBMISSION LOGIC
    if (request.method == 'POST' and request.POST.get('action') != 'start_assessment') or remaining_time <= 0:
        score = 0
        total_questions = questions.count()
        
        if request.method == 'POST':
            for q in questions:
                user_answer = request.POST.get(f'question_{q.id}')
                try:
                    submitted_option = int(user_answer)
                except (TypeError, ValueError):
                    submitted_option = None

                if submitted_option == q.correct_option:
                    score += 1
        
        percentage = (score / total_questions) * 100 if total_questions > 0 else 0

        # Mark Session as submitted
        session.score = percentage
        session.status = 'submitted'
        session.save()

        # PASS CONDITION: 75%
        if percentage >= 75:
            Progress.objects.get_or_create(student=request.user, video=video, passed=True)
            
            if video.order == enrollment.current_lesson_index:
                enrollment.current_lesson_index += 1
                enrollment.save()
            
            return render(request, 'quiz_result.html', {'status': 'passed', 'video': video, 'score': int(percentage)})
        else:
            return render(request, 'quiz_result.html', {'status': 'failed', 'video': video, 'score': int(percentage)})

    # 4. RENDER PROCTORED PAGE
    return render(request, 'take_quiz.html', {
        'questions': questions, 
        'video': video,
        'session': session,
        'remaining_time': int(remaining_time),
        'exam_not_started': False,
    })

@login_required
def start_exam(request, exam_id):
    from .models import Exam, ExamQuestion, ExamAssignment, QuizSession
    exam = get_object_or_404(Exam, id=exam_id)
    
    # Verify assignment
    assignment = get_object_or_404(ExamAssignment, student=request.user, exam=exam)
    
    if assignment.status == 'completed':
        messages.info(request, "This assessment has already been graded and published.")
        return redirect('profile')

    if assignment.status == 'submitted':
        messages.info(request, "Your assessment is submitted and waiting for evaluation.")
        return redirect('profile')

    questions = exam.questions.all()
    if not questions.exists():
        messages.error(request, "This exam paper has no questions yet. Please contact your conductor.")
        return redirect('profile')

    # 1. SETUP PROCTORING SESSION
    session, created = QuizSession.objects.get_or_create(
        student=request.user,
        exam=exam,
        defaults={'status': 'ongoing'}
    )
    
    if request.method == 'POST' and request.POST.get('action') == 'start_assessment':
        session.end_time = timezone.now() + timedelta(minutes=exam.duration_minutes)
        session.status = 'ongoing'
        session.save(update_fields=['end_time', 'status'])
        request.session[f'assessment_started_{session.id}'] = True
        return redirect('start_exam', exam_id=exam.id)

    if session.status == 'ongoing' and session.end_time and not request.session.get(f'assessment_started_{session.id}'):
        session.end_time = None
        session.save(update_fields=['end_time'])

    exam_not_started = not session.end_time
    if exam_not_started:
        return render(request, 'take_quiz.html', {
            'questions': questions,
            'exam_title': exam.title,
            'session': session,
            'remaining_time': exam.duration_minutes * 60,
            'exam_not_started': True,
        })

    remaining_time = (session.end_time - timezone.now()).total_seconds()

    # 3. GRADING & SUBMISSION LOGIC
    if (request.method == 'POST' and request.POST.get('action') != 'start_assessment') or remaining_time <= 0:
        from .models import StudentAnswer
        total_score = 0
        max_possible = sum(q.points for q in questions)
        has_essay = questions.filter(q_type='essay').exists()
        
        if request.method == 'POST':
            for q in questions:
                earned = 0
                is_correct = False
                user_val = ""
                essay_text = ""
                
                if q.q_type == 'mcq':
                    user_val = request.POST.get(f'question_{q.id}')
                    if user_val == q.correct_answer:
                        earned = q.points
                        is_correct = True
                
                elif q.q_type == 'multi':
                    user_list = request.POST.getlist(f'question_{q.id}')
                    user_val = ",".join(sorted(user_list))
                    # All correct indices must match exactly
                    if user_val == q.correct_answer:
                        earned = q.points
                        is_correct = True
                
                elif q.q_type == 'essay':
                    essay_text = request.POST.get(f'question_{q.id}', '')
                    earned = 0 # Manual review required
                    is_correct = None
                
                # Save answer record
                StudentAnswer.objects.update_or_create(
                    session=session,
                    question=q,
                    defaults={
                        'selected_options': user_val,
                        'essay_text': essay_text,
                        'is_correct': is_correct,
                        'marks_earned': earned
                    }
                )
                total_score += earned
        
        percentage = (total_score / max_possible) * 100 if max_possible > 0 else 0

        # Mark Session as submitted
        session.score = percentage
        session.status = 'submitted'
        # Exam scores are published only after a teacher/conductor review.
        session.is_reviewed = False
        session.save()

        # Keep the result hidden from the student until grading is published.
        assignment.status = 'submitted'
        assignment.final_score = None
        assignment.save()

        return render(request, 'quiz_result.html', {
            'status': 'pending', 
            'exam': exam, 
            'score': None,
            'has_essay': True
        })

    # 4. RENDER PROCTORED PAGE (Generic support in take_quiz.html)
    return render(request, 'take_quiz.html', {
        'questions': questions, 
        'exam_title': exam.title,
        'session': session,
        'remaining_time': int(remaining_time),
        'exam_not_started': False,
    })

# ==================================================================
# 🚀 AI PROCTORING RECEIVER (UPDATED FOR QUIZZES)
# ==================================================================
import json
import base64
import cv2
import numpy as np
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.core.cache import cache
from .models import QuizSession, ProctoringLog

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

# 🚀 Load OpenCV AI Models globally to make it super fast
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
alt_face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
profile_face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# Secondary detector to reduce “no face” false negatives when a face is masked or at an angle.
hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

YOLO_MODEL = None
YOLO_MODEL_PATH = str(settings.BASE_DIR / 'yolov8n.pt')
YOLO_PERSON_CLASS_ID = 0
YOLO_PHONE_CLASS_ID = 67
YOLO_PERSON_CONFIDENCE = 0.50
YOLO_PHONE_CONFIDENCE = 0.35


FRAME_CONFIRMATION_RULES = {
    'phone_detected': {'needed': 2, 'timeout': 20},
    'multi_face': {'needed': 2, 'timeout': 20},
    'no_face': {'needed': 3, 'timeout': 25},
    'head_pose': {'needed': 3, 'timeout': 25},
    'gaze_deviation': {'needed': 4, 'timeout': 25},
}

EVENT_CONFIRMATION_RULES = {
    'tab_switch': {'needed': 1, 'timeout': 15},
    'window_blur': {'needed': 2, 'timeout': 10},
    'camera_stalled': {'needed': 2, 'timeout': 20},
}


def _rect_overlap_ratio(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    smaller_area = max(1, min(aw * ah, bw * bh))
    return overlap / smaller_area


def _dedupe_boxes(boxes, overlap_threshold=0.35):
    kept = []
    for box in sorted(boxes, key=lambda item: item[2] * item[3], reverse=True):
        if all(_rect_overlap_ratio(box, existing) < overlap_threshold for existing in kept):
            kept.append(box)
    return kept


def _frame_is_usable(gray_frame):
    brightness = float(np.mean(gray_frame))
    contrast = float(np.std(gray_frame))
    return 35 <= brightness <= 225 and contrast >= 18


def _get_yolo_model():
    global YOLO_MODEL
    if YOLO is None:
        return None
    if YOLO_MODEL is None:
        try:
            YOLO_MODEL = YOLO(YOLO_MODEL_PATH)
        except Exception as exc:
            print("YOLO load error:", exc)
            YOLO_MODEL = False
    return YOLO_MODEL if YOLO_MODEL is not False else None


def _detect_yolo_objects(frame):
    model = _get_yolo_model()
    if model is None:
        return [], []

    try:
        results = model.predict(
            frame,
            imgsz=416,
            conf=min(YOLO_PHONE_CONFIDENCE, YOLO_PERSON_CONFIDENCE),
            classes=[YOLO_PERSON_CLASS_ID, YOLO_PHONE_CLASS_ID],
            verbose=False,
            device='cpu',
        )
    except Exception as exc:
        print("YOLO detection error:", exc)
        return [], []

    person_boxes = []
    phone_boxes = []
    if not results:
        return person_boxes, phone_boxes

    boxes = results[0].boxes
    if boxes is None:
        return person_boxes, phone_boxes

    for box in boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        x1, y1, x2, y2 = [int(value) for value in box.xyxy[0]]
        detected_box = (x1, y1, max(1, x2 - x1), max(1, y2 - y1), confidence)

        if class_id == YOLO_PERSON_CLASS_ID and confidence >= YOLO_PERSON_CONFIDENCE:
            person_boxes.append(detected_box)
        elif class_id == YOLO_PHONE_CLASS_ID and confidence >= YOLO_PHONE_CONFIDENCE:
            phone_boxes.append(detected_box)

    return person_boxes, phone_boxes


def _phone_is_near_person_or_face(phone_box, person_boxes, face_boxes):
    px, py, pw, ph, _ = phone_box
    phone_rect = (px, py, pw, ph)
    for fx, fy, fw, fh in face_boxes:
        near_face_x = fx - 160 <= px <= fx + fw + 160
        near_face_y = fy - 60 <= py <= fy + fh + 200
        if near_face_x and near_face_y:
            return True
    for bx, by, bw, bh, _ in person_boxes:
        inside_person_x = bx - 40 <= px <= bx + bw + 40
        inside_person_y = by - 40 <= py <= by + bh + 40
        if inside_person_x and inside_person_y:
            return True
    return False


def _cache_latest_frame_snapshot(session_id, frame):
    ok, buffer = cv2.imencode('.jpg', frame)
    if ok:
        cache.set(f'proctor_latest_frame_{session_id}', buffer.tobytes(), timeout=180)


def _get_latest_frame_snapshot_file(session_id):
    img_bytes = cache.get(f'proctor_latest_frame_{session_id}')
    if not img_bytes:
        return None
    return ContentFile(
        img_bytes,
        name=f"event_evidence_{session_id}_{int(np.random.rand() * 100000)}.jpg",
    )


def _detect_faces(gray_frame):
    """
    Cascade ensemble with eye-validation to drop false positives
    (e.g., phones or background mistaken as faces).
    """
    frame_h, frame_w = gray_frame.shape[:2]
    cascades = (face_cascade, alt_face_cascade, profile_face_cascade)
    all_faces = []
    for cascade in cascades:
        faces = cascade.detectMultiScale(
            gray_frame,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(70, 70)
        )
        for (x, y, w, h) in faces:
            area_ratio = (w * h) / float(frame_w * frame_h)
            aspect = w / float(h) if h else 0
            if area_ratio < 0.015 or area_ratio > 0.45 or not 0.65 <= aspect <= 1.35:
                continue
            roi = gray_frame[y:y+h, x:x+w]
            eyes = eye_cascade.detectMultiScale(
                roi, scaleFactor=1.1, minNeighbors=5, minSize=(14, 14)
            )
            upper_y = y + int(h * 0.65)
            if len(eyes) > 0:
                all_faces.append((x, y, w, h))
            elif y < upper_y and area_ratio >= 0.035:
                all_faces.append((x, y, w, h))
    return _dedupe_boxes(all_faces)


def _detect_people(frame):
    """
    Lightweight pedestrian detector (HOG+SVM). Helps confirm presence of humans
    even if faces are not picked up by cascades.
    """
    people, weights = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
    filtered = []
    filtered_weights = []
    frame_area = frame.shape[0] * frame.shape[1]
    for person, weight in zip(people, weights):
        x, y, w, h = person
        area_ratio = (w * h) / float(frame_area)
        if area_ratio >= 0.08 and weight >= 0.45:
            filtered.append((x, y, w, h))
            filtered_weights.append(float(weight))
    return filtered, filtered_weights


def _detect_phone(frame, face_boxes):
    """
    Lightweight heuristic: look for a vertical rectangle (phone-like) close to a detected face.
    Avoids heavyweight object detectors while still flagging obvious phone use.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 80, 200)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = frame.shape[0] * frame.shape[1]

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 0.006 * frame_area or area > 0.055 * frame_area:
            continue

        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if 4 <= len(approx) <= 6:
            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / float(h) if h else 0
            fill_ratio = area / float(max(1, w * h))
            if 0.38 <= aspect <= 0.82 and 0.55 <= fill_ratio <= 1.05:
                if face_boxes:
                    for (fx, fy, fw, fh) in face_boxes:
                        near_face_x = fx - 120 <= x <= fx + fw + 120
                        near_face_y = fy - 30 <= y <= fy + fh + 160
                        away_from_face_center = _rect_overlap_ratio((x, y, w, h), (fx, fy, fw, fh)) < 0.25
                        if near_face_x and near_face_y and away_from_face_center:
                            return True, (x, y, w, h)
    return False, None


def _log_proctoring_violation(session, violation_type, confidence, frame=None, label=None):
    if session.proctoring_logs.count() >= 25:
        return False

    evidence_file = None
    if frame is not None:
        if label:
            cv2.putText(frame, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        ok, buffer = cv2.imencode('.jpg', frame)
        if ok:
            evidence_file = ContentFile(
                buffer.tobytes(),
                name=f"evidence_{session.id}_{int(np.random.rand() * 100000)}.jpg",
            )

    ProctoringLog.objects.create(
        session=session,
        violation_type=violation_type,
        confidence_score=confidence,
        evidence_image=evidence_file,
    )

    if session.status != 'flagged':
        session.status = 'flagged'
        session.save(update_fields=['status'])

    return True


def _should_log_confirmed_violation(session_id, violation_type, rules):
    rule = rules.get(violation_type, {'needed': 2, 'timeout': 20})
    key = f'proctor_violation_{session_id}_{violation_type}'
    count = cache.get(key, 0) + 1
    cache.set(key, count, timeout=rule['timeout'])
    if count >= rule['needed']:
        cache.delete(key)
        return True
    return False


def _reset_frame_violation_state(session_id):
    for violation_type in FRAME_CONFIRMATION_RULES:
        cache.delete(f'proctor_violation_{session_id}_{violation_type}')


def _reset_event_state(session_id, event_type):
    cache.delete(f'proctor_violation_{session_id}_{event_type}')

def process_quiz_frame(request, session_id):
    if request.method == 'POST':
        try:
            session = QuizSession.objects.get(id=session_id, student=request.user)
            data = json.loads(request.body)
            event_type = data.get('event')

            if event_type:
                allowed_events = {
                    'tab_switch': ('tab_switch', 0.98, 'Browser tab/window changed'),
                    'window_blur': ('tab_switch', 0.92, 'Browser window lost focus'),
                    'camera_stalled': ('no_face', 0.9, 'Camera feed stalled or unavailable'),
                }
                if event_type not in allowed_events:
                    return JsonResponse({'status': 'ignored', 'violation': False})

                violation_type, confidence, message = allowed_events[event_type]
                if not _should_log_confirmed_violation(session.id, event_type, EVENT_CONFIRMATION_RULES):
                    return JsonResponse({
                        'status': 'success',
                        'violation': False,
                        'type': violation_type,
                        'message': 'Browser event observed; waiting for confirmation.',
                    })

                _reset_event_state(session.id, event_type)
                evidence_file = _get_latest_frame_snapshot_file(session.id)
                if evidence_file is not None:
                    ProctoringLog.objects.create(
                        session=session,
                        violation_type=violation_type,
                        confidence_score=confidence,
                        evidence_image=evidence_file,
                    )
                    if session.status != 'flagged':
                        session.status = 'flagged'
                        session.save(update_fields=['status'])
                    logged = True
                else:
                    logged = _log_proctoring_violation(session, violation_type, confidence)
                return JsonResponse({
                    'status': 'success',
                    'violation': logged,
                    'type': violation_type,
                    'confidence': confidence,
                    'message': message,
                })

            image_data = data.get('image')

            if image_data:
                # 1. Decode the image from the browser
                format, imgstr = image_data.split(';base64,') 
                ext = format.split('/')[-1]
                img_bytes = base64.b64decode(imgstr)

                # Convert to OpenCV format
                np_arr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is None:
                    return JsonResponse({'status': 'error', 'message': 'Invalid frame'}, status=400)

                frame = cv2.resize(frame, (640, 480))
                _cache_latest_frame_snapshot(session.id, frame)
                raw_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(raw_gray)

                # ==========================================================
                # 🚀 ADVANCED BEHAVIOUR ANALYSIS ENGINE
                # ==========================================================
                violation_detected = False 
                violation_type = None
                confidence = 0.0

                # --- DETECTION STAGE --------------------------------------
                faces = _detect_faces(gray)
                people, people_weights = _detect_people(frame)
                phone_found, phone_box = _detect_phone(frame, faces)
                yolo_people, yolo_phones = _detect_yolo_objects(frame)
                yolo_phone = next(
                    (
                        phone
                        for phone in yolo_phones
                        if phone[4] >= 0.50 or _phone_is_near_person_or_face(phone, yolo_people, faces)
                    ),
                    None,
                )
                frame_usable = _frame_is_usable(raw_gray)

                # 1) YOLO phone detection is more reliable than shape guessing.
                if yolo_phone:
                    violation_detected = True
                    violation_type = 'phone_detected'
                    confidence = round(yolo_phone[4], 2)
                    px, py, pw, ph, _ = yolo_phone
                    cv2.rectangle(frame, (px, py), (px+pw, py+ph), (0, 0, 255), 3)
                    cv2.putText(frame, "ALERT: PHONE DETECTED", (px, max(30, py-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                # 2) YOLO person count handles multiple people better than face cascades.
                elif len(yolo_people) > 1:
                    violation_detected = True
                    violation_type = 'multi_face'
                    confidence = round(max(person[4] for person in yolo_people), 2)
                    cv2.putText(frame, "ALERT: MULTIPLE PERSONS", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    for (x, y, w, h, _) in yolo_people:
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 3)

                # 3) CLEAR MULTI-FACE (only if real face detections >1)
                elif len(faces) > 1:
                    violation_detected = True
                    violation_type = 'multi_face'
                    confidence = 0.96
                    cv2.putText(frame, "ALERT: MULTIPLE PERSONS", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    for (x, y, w, h) in faces:
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 3)

                # 4) Fallback phone heuristic when YOLO misses a very obvious phone.
                elif phone_found:
                    violation_detected = True
                    violation_type = 'phone_detected'
                    confidence = 0.90
                    px, py, pw, ph = phone_box
                    cv2.rectangle(frame, (px, py), (px+pw, py+ph), (0, 0, 255), 3)
                    cv2.putText(frame, "ALERT: PHONE DETECTED", (px, max(30, py-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                # 5) NO FACE FOUND
                elif len(faces) == 0:
                    if not frame_usable:
                        violation_detected = True
                        violation_type = 'no_face'
                        confidence = 0.70
                        cv2.putText(frame, "WEBCAM QUALITY TOO LOW", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                    elif len(people) > 1:
                        violation_detected = True
                        violation_type = 'multi_face'
                        confidence = float(np.clip(max(people_weights, default=0.9), 0.75, 0.95))
                        cv2.putText(frame, "ALERT: MULTIPLE PERSONS", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                        for (x, y, w, h) in people:
                            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 3)
                    elif len(people) == 1:
                        violation_detected = True
                        violation_type = 'head_pose'
                        confidence = 0.78
                        (x, y, w, h) = people[0]
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 165, 255), 3)
                        cv2.putText(frame, "FACE NOT VISIBLE / ANGLED", (x, max(30, y-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                    else:
                        violation_detected = True
                        violation_type = 'no_face'
                        confidence = 0.95
                        cv2.putText(frame, "ALERT: NO FACE DETECTED", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

                # 4) ONE FACE: check eyes (looking away / phone down)
                else:
                    x, y, w, h = faces[0]
                    roi_gray = gray[y:y+h, x:x+w] # Focus AI only on the face area
                    
                    eyes = eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=5, minSize=(15, 15))
                    face_center_x = x + (w / 2)
                    face_center_y = y + (h / 2)
                    looking_edge = (
                        face_center_x < frame.shape[1] * 0.22 or
                        face_center_x > frame.shape[1] * 0.78 or
                        face_center_y < frame.shape[0] * 0.18 or
                        face_center_y > frame.shape[0] * 0.78
                    )
                    
                    if len(eyes) == 0 and looking_edge:
                        violation_detected = True
                        violation_type = 'gaze_deviation'
                        confidence = 0.78
                        
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 165, 255), 3) # Orange box
                        cv2.putText(frame, "LOOKING AWAY / PHONE", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

                # ==========================================================

                # Save the evidence if a rule was broken
                if violation_detected:
                    readable = {
                        'no_face': 'No face detected in repeated checks',
                        'multi_face': 'Multiple persons detected',
                        'gaze_deviation': 'Looking away from screen repeatedly',
                        'head_pose': 'Face hidden or angled repeatedly',
                        'phone_detected': 'Phone detected in frame',
                    }
                    if _should_log_confirmed_violation(session.id, violation_type, FRAME_CONFIRMATION_RULES):
                        logged = _log_proctoring_violation(session, violation_type, confidence, frame=frame)
                        return JsonResponse({
                            'status': 'success',
                            'violation': logged,
                            'type': violation_type,
                            'confidence': round(confidence, 2),
                            'message': readable.get(violation_type, 'Suspicious behaviour')
                        })

                    return JsonResponse({
                        'status': 'success',
                        'violation': False,
                        'type': violation_type,
                        'message': 'Suspicious frame observed; waiting for confirmation.'
                    })

                _reset_frame_violation_state(session.id)
                return JsonResponse({'status': 'success', 'violation': False})

        except Exception as e:
            print("AI Error:", str(e))
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return JsonResponse({'status': 'invalid request'}, status=400)


@login_required
def complete_lesson(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    enrollment = get_object_or_404(Enrollment, student=request.user, course=video.course)

    Progress.objects.get_or_create(student=request.user, video=video, passed=True)

    if video.order == enrollment.current_lesson_index:
        enrollment.current_lesson_index += 1
        enrollment.save()

    total_videos = video.course.videos.count()
    passed_videos = Progress.objects.filter(student=request.user, video__course=video.course, passed=True).count()

    if passed_videos >= total_videos and not enrollment.is_completed:
        enrollment.is_completed = True
        enrollment.completed_at = timezone.now()
        enrollment.save()
        messages.success(request, "Course Completed! Certificate Unlocked.")

    next_order = video.order + 1
    next_video = Video.objects.filter(course=video.course, order=next_order).first()
    
    if next_video:
        return redirect('course_viewer', course_id=video.course.id, video_order=next_order)
    else:
        return redirect('course_viewer', course_id=video.course.id, video_order=video.order)

@login_required
def certificate_view(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    enrollment = get_object_or_404(Enrollment, student=request.user, course=course)
    
    if not enrollment.is_completed:
        messages.error(request, "You must complete the course to view the certificate.")
        return redirect('course_viewer', course_id=course.id, video_order=1)
        
    return render(request, 'certificate.html', {'course': course, 'enrollment': enrollment})

@login_required
def add_review(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            already_reviewed = Review.objects.filter(course=course, user=request.user).exists()
            if already_reviewed:
                messages.error(request, "You have already reviewed this course!")
            else:
                review = form.save(commit=False)
                review.course = course
                review.user = request.user
                review.save()
                messages.success(request, "Review added successfully!")
                
    return redirect('course_viewer', course_id=course.id, video_order=1)

@login_required
def add_comment(request, video_id, parent_id=None):
    video = get_object_or_404(Video, id=video_id)
    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.video = video
            comment.user = request.user
            
            if parent_id:
                parent_comment = get_object_or_404(Comment, id=parent_id)
                comment.parent = parent_comment
                
            comment.save()
            messages.success(request, "Response posted!")
            
    return redirect('course_viewer', course_id=video.course.id, video_order=video.order)


# ------------------------------------------------------------------
# INSTRUCTOR / ADMIN PANEL
# ------------------------------------------------------------------
@user_passes_test(is_admin)
def instructor_dashboard(request):
    students = User.objects.filter(is_student=True, is_superuser=False).order_by('-date_joined')
    total_students_count = students.count()
    
    courses = Course.objects.annotate(
        enrolled_count=Count('enrolled_students', distinct=True),
        video_count=Count('videos', distinct=True)
    )
    
    recent_activity = Progress.objects.select_related('student', 'video').order_by('-id')[:10]
    
    # REPLACED ExamSession WITH QuizSession
    quiz_sessions = QuizSession.objects.exclude(status='ongoing').order_by('-start_time')
    examiners = User.objects.filter(is_examiner=True).order_by('-date_joined')

    # Add Revenue calculations and Seaborn chart generation
    from courses.models import Payment
    from courses.utils import generate_revenue_chart
    from django.db.models import Sum

    revenue_agg = Payment.objects.filter(status='completed').aggregate(total=Sum('amount'))
    total_revenue = float(revenue_agg['total'] or 0.0)
    total_sales = Payment.objects.filter(status='completed').count()
    recent_sales = Payment.objects.filter(status='completed').select_related('student', 'course').order_by('-payment_date')[:10]

    chart_url = ""
    try:
        chart_url = generate_revenue_chart()
    except Exception as e:
        print(f"Error generating Seaborn revenue chart: {e}")

    from .forms import CourseForm
    context = {
        'courses': courses,
        'total_students': total_students_count,
        'all_students': students,
        'recent_activity': recent_activity,
        'quiz_sessions': quiz_sessions, 
        'examiners': examiners,
        'total_revenue': total_revenue,
        'total_sales': total_sales,
        'recent_sales': recent_sales,
        'chart_url': chart_url,
        'course_form': CourseForm(),
    }
    return render(request, 'dashboard.html', context)


@user_passes_test(is_admin)
def toggle_portal_user_status(request, user_id):
    portal_user = get_object_or_404(User, id=user_id, is_superuser=False)
    target_tab = '/dashboard/#students' if portal_user.is_student else '/dashboard/#examiners'
    if request.method != 'POST':
        return redirect(target_tab)

    if portal_user.id == request.user.id:
        messages.error(request, "You cannot block your own account.")
        return redirect(target_tab)

    portal_user.is_active = not portal_user.is_active
    portal_user.save(update_fields=['is_active'])

    status = "activated" if portal_user.is_active else "blocked"
    messages.success(request, f"{portal_user.username} has been {status}.")
    return redirect(target_tab)


@user_passes_test(is_admin)
def delete_portal_user(request, user_id):
    portal_user = get_object_or_404(User, id=user_id, is_superuser=False)
    target_tab = '/dashboard/#students' if portal_user.is_student else '/dashboard/#examiners'
    if request.method != 'POST':
        return redirect(target_tab)

    if portal_user.id == request.user.id:
        messages.error(request, "You cannot delete your own account.")
        return redirect(target_tab)

    username = portal_user.username
    portal_user.delete()
    messages.success(request, f"{username} has been deleted.")
    return redirect(target_tab)


@user_passes_test(is_admin)
def admin_proctoring_dashboard(request):
    sessions = QuizSession.objects.prefetch_related('proctoring_logs').order_by('-start_time')
    for session in sessions:
        session.risk_report = calculate_risk_report(session.proctoring_logs.all())
    return render(request, 'admin_proctoring_dashboard.html', {'sessions': sessions})

@user_passes_test(is_admin)
def review_quiz_session(request, session_id):
    session = get_object_or_404(QuizSession, id=session_id)
    logs = session.proctoring_logs.all().order_by('timestamp')
    risk_report = calculate_risk_report(logs)

    if request.method == 'POST':
        action = request.POST.get('action')
        admin_notes = request.POST.get('admin_notes', '')

        session.admin_notes = admin_notes
        session.is_reviewed = True

        if action == 'approve':
            session.status = 'submitted'
            messages.success(request, f"Session for {session.student.username} approved.")
        elif action == 'disqualify':
            session.status = 'disqualified'
            messages.error(request, f"Student {session.student.username} has been disqualified.")
        
        session.save()
        return redirect('admin_proctoring_dashboard')

    context = {
        'session': session,
        'logs': logs,
        'risk_report': risk_report,
    }
    return render(request, 'review_quiz_session.html', context)

@user_passes_test(is_admin)
def create_course(request):
    if request.method == 'POST':
        form = CourseForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('/dashboard/#content')
    else:
        form = CourseForm()
    return render(request, 'create_course.html', {'form': form})

@user_passes_test(is_admin)
def edit_course(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.method == 'POST':
        form = CourseForm(request.POST, request.FILES, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, f"Course '{course.title}' updated successfully.")
            return redirect('/dashboard/#content')
    return redirect('/dashboard/#content')

@user_passes_test(is_admin)
def add_video(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.method == 'POST':
        form = VideoForm(request.POST, request.FILES) 
        if form.is_valid():
            video = form.save(commit=False)
            video.course = course
            video.save()
            return redirect('/dashboard/#content')
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
                return redirect('/dashboard/#content')
    else:
        form = QuizForm()
    return render(request, 'add_quiz.html', {'form': form, 'video': video})

@user_passes_test(is_admin)
def edit_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if request.method == 'POST':
        form = VideoForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            form.save()
            return redirect('/dashboard/#content')
    else:
        form = VideoForm(instance=video)
    return render(request, 'add_video.html', {'form': form, 'course': video.course, 'is_edit': True})

@user_passes_test(is_admin)
def delete_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    video.delete()
    return redirect('/dashboard/#content')

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
    student = get_object_or_404(User, id=student_id, is_superuser=False)
    student.delete()
    return redirect('/dashboard/#students')

@user_passes_test(is_admin)
def delete_student(request, student_id):
    student = get_object_or_404(User, id=student_id)
    if not student.is_superuser: 
        student.delete()
    return redirect('/dashboard/#students')
