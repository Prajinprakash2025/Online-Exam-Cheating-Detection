from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Count, Q
from courses.models import Course, Video, Quiz, QuizSession, Exam, ExamQuestion, ExamAssignment, StudentAnswer
from courses.forms import QuizForm
from courses.proctoring import calculate_risk_report
from .models import TeacherStudentAssignment
from .forms import StudentCreateForm

import random
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()

TEACHER_LOGIN_OTP_MINUTES = 10


def _clear_teacher_login_otp(request):
    for key in (
        'teacher_login_user_id',
        'teacher_login_email',
        'teacher_login_otp',
        'teacher_login_otp_expires_at',
    ):
        request.session.pop(key, None)


def _print_teacher_otp(purpose, email, otp):
    print("\n" + "=" * 64)
    print(f"ExamGate {purpose} OTP for {email}: {otp}")
    print("=" * 64 + "\n")


def _send_teacher_otp(email, subject, message, otp, purpose):
    _print_teacher_otp(purpose, email, otp)

    backend = getattr(settings, 'EMAIL_BACKEND', '')
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or getattr(settings, 'EMAIL_HOST_USER', '')
    can_send_email = bool(from_email) or 'console' in backend or 'locmem' in backend

    if not can_send_email:
        return

    try:
        send_mail(
            subject,
            message,
            from_email,
            [email],
            fail_silently=False,
        )
    except Exception as exc:
        if not settings.DEBUG:
            raise
        print(f"ExamGate OTP email delivery skipped in DEBUG after error: {exc}")


def _teacher_otp_context(request):
    expires_at = request.session.get('teacher_login_otp_expires_at')
    otp_email = request.session.get('teacher_login_email')

    if not expires_at or not otp_email:
        return {'otp_sent': False}

    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        _clear_teacher_login_otp(request)
        return {'otp_sent': False}

    if timezone.now().timestamp() > expires_at:
        _clear_teacher_login_otp(request)
        return {'otp_sent': False}

    return {'otp_sent': True, 'otp_email': otp_email}


def teacher_login(request):
    if request.GET.get('reset') == '1':
        _clear_teacher_login_otp(request)
        return redirect('teacher_login')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'verify_otp':
            entered_otp = (request.POST.get('otp') or '').strip()
            saved_otp = str(request.session.get('teacher_login_otp') or '')
            user_id = request.session.get('teacher_login_user_id')
            expires_at = request.session.get('teacher_login_otp_expires_at')

            if not user_id or not saved_otp or not expires_at:
                messages.error(request, "Please request a fresh login OTP.")
                return redirect('teacher_login')

            try:
                expires_at = float(expires_at)
            except (TypeError, ValueError):
                _clear_teacher_login_otp(request)
                messages.error(request, "Please request a fresh login OTP.")
                return redirect('teacher_login')

            if timezone.now().timestamp() > expires_at:
                _clear_teacher_login_otp(request)
                messages.error(request, "Your login OTP expired. Please request a new one.")
                return redirect('teacher_login')

            if entered_otp != saved_otp:
                messages.error(request, "Invalid OTP. Please try again.")
                return render(request, 'teachers/teacher_login.html', _teacher_otp_context(request))

            user = get_object_or_404(User, id=user_id, is_teacher=True)
            login(request, user)
            _clear_teacher_login_otp(request)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect('teacher_dashboard')

        email = (request.POST.get('email') or '').strip().lower()
        user = User.objects.filter(email__iexact=email, is_teacher=True).first()

        if not user:
            messages.error(request, "No teacher account was found for that email.")
            return render(request, 'teachers/teacher_login.html', {'otp_sent': False})

        otp = f"{random.randint(100000, 999999)}"
        subject = 'Your ExamGate Teacher Login OTP'
        message = (
            f"Hello {user.first_name or user.username},\n\n"
            f"Your ExamGate teacher login OTP is: {otp}\n\n"
            f"This code is valid for {TEACHER_LOGIN_OTP_MINUTES} minutes."
        )

        try:
            _send_teacher_otp(user.email, subject, message, otp, 'teacher login')
        except Exception as exc:
            messages.error(request, f"Could not send OTP email: {exc}")
            return render(request, 'teachers/teacher_login.html', {'otp_sent': False})

        request.session['teacher_login_user_id'] = user.id
        request.session['teacher_login_email'] = user.email
        request.session['teacher_login_otp'] = otp
        request.session['teacher_login_otp_expires_at'] = (
            timezone.now() + timedelta(minutes=TEACHER_LOGIN_OTP_MINUTES)
        ).timestamp()

        messages.success(request, f"OTP generated for {user.email}. Check your terminal for the code.")
        return render(request, 'teachers/teacher_login.html', _teacher_otp_context(request))

    return render(request, 'teachers/teacher_login.html', _teacher_otp_context(request))


@login_required
def teacher_logout(request):
    logout(request)
    return redirect('teacher_login')


def is_teacher(user):
    return user.is_authenticated and user.is_teacher


@login_required
@user_passes_test(is_teacher)
def teacher_dashboard(request):
    teacher = request.user
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'register_student':
            from courses.models import User
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            email = request.POST.get('email')
            course_id = request.POST.get('course')
            
            # Check if user already exists
            student = User.objects.filter(email=email).first()
            
            if student:
                # If they exist and are a student, just link them
                if student.is_student:
                    assignment, created = TeacherStudentAssignment.objects.get_or_create(
                        teacher=teacher, 
                        student=student, 
                        course_id=course_id
                    )
                    if created:
                        messages.success(request, f"Student {student.get_full_name() or student.username} is now linked to your roster.")
                    else:
                        messages.info(request, f"Student {student.username} is already in your roster.")
                else:
                    messages.error(request, "This email is associated with a non-student account.")
            else:
                # Create new user without password (log in via OTP)
                student = User.objects.create_user(
                    username=email, 
                    email=email, 
                    first_name=first_name, 
                    last_name=last_name,
                    is_student=True
                )
                student.set_unusable_password()
                student.save()
                
                if course_id:
                    course = get_object_or_404(Course, id=course_id)
                    TeacherStudentAssignment.objects.create(teacher=teacher, student=student, course=course)
                messages.success(request, f"New student account created for {first_name} {last_name}.")
            
            return redirect('/teachers/dashboard/#students')

        elif action == 'create_exam':
            title = request.POST.get('title')
            course_id = request.POST.get('course')
            duration = request.POST.get('duration')
            passing_score = request.POST.get('passing_score')
            description = request.POST.get('description')
            
            course = get_object_or_404(Course, id=course_id)
            exam = Exam.objects.create(
                title=title,
                course=course,
                duration_minutes=duration,
                passing_score=passing_score,
                description=description,
                created_by=teacher
            )
            messages.success(request, f"Exam Paper '{title}' designed. Now add your questions.")
            return redirect('teacher_exam_questions', exam_id=exam.id)

        elif action == 'assign_exam':
            exam_id = request.POST.get('exam_id')
            # Extract student IDs from comma separated string or list
            raw_student_ids = request.POST.get('student_ids', '')
            if ',' in raw_student_ids:
                student_ids = [sid.strip() for sid in raw_student_ids.split(',') if sid.strip()]
            else:
                student_ids = request.POST.getlist('student_ids')
                
            exam = get_object_or_404(Exam, id=exam_id, created_by=teacher)
            allowed_student_ids = set(str(student_id) for student_id in TeacherStudentAssignment.objects.filter(
                teacher=teacher
            ).values_list('student_id', flat=True))
            
            count = 0
            for sid in student_ids:
                if sid not in allowed_student_ids:
                    continue
                from courses.models import User
                student = get_object_or_404(User, id=sid, is_student=True)
                _assignment, created = ExamAssignment.objects.get_or_create(exam=exam, student=student)
                if created:
                    count += 1
            
            messages.success(request, f"Successfully assigned '{exam.title}' to {count} students.")
            return redirect('/teachers/dashboard/#students')

        elif action == 'edit_student':
            student_id = request.POST.get('student_id')
            from courses.models import User
            student = get_object_or_404(User, id=student_id, is_student=True)
            student.first_name = request.POST.get('first_name', student.first_name)
            student.last_name = request.POST.get('last_name', student.last_name)
            student.email = request.POST.get('email', student.email)
            student.save()
            messages.success(request, f"Student {student.username} details updated.")
            return redirect('/teachers/dashboard/#students')

        elif action == 'edit_exam':
            exam_id = request.POST.get('exam_id')
            exam = get_object_or_404(Exam, id=exam_id, created_by=teacher)
            exam.title = request.POST.get('title', exam.title)
            exam.duration_minutes = request.POST.get('duration', exam.duration_minutes)
            exam.passing_score = request.POST.get('passing_score', exam.passing_score)
            exam.description = request.POST.get('description', exam.description)
            exam.save()
            messages.success(request, f"Exam '{exam.title}' updated.")
            return redirect('/teachers/dashboard/#exams')

    # Data for the dashboard
    assignments = TeacherStudentAssignment.objects.filter(teacher=teacher).select_related('student', 'course')
    course_ids = assignments.values_list('course_id', flat=True).distinct()
    
    # Filter subjects created by the teacher's managing conductor/examiner OR admin-created ones
    from examiners.models import ExaminerTeacherAssignment
    examiner_assignment = ExaminerTeacherAssignment.objects.filter(teacher=teacher).first()
    if examiner_assignment:
        all_subjects = Course.objects.filter(
            Q(created_by=examiner_assignment.examiner) | Q(created_by__isnull=True)
        ).order_by('-created_at')
    else:
        all_subjects = Course.objects.filter(created_by__isnull=True).order_by('-created_at')
    
    videos = Video.objects.filter(course_id__in=course_ids).order_by('course__title', 'order')
    
    # Recent sessions for this teacher's students
    assigned_student_ids = [a.student_id for a in assignments]
    recent_sessions = QuizSession.objects.filter(
        student_id__in=assigned_student_ids
    ).exclude(status='ongoing').select_related('student', 'video__course', 'exam__course').order_by('-start_time')[:10]
    review_count = QuizSession.objects.filter(
        student_id__in=assigned_student_ids
    ).exclude(status='ongoing').filter(is_reviewed=False).count()
    flagged_count = QuizSession.objects.filter(
        student_id__in=assigned_student_ids,
        status='flagged',
    ).count()

    exam_assignments_by_student = {}
    exam_assignments = ExamAssignment.objects.filter(
        student_id__in=assigned_student_ids,
        exam__created_by=teacher,
    ).select_related('exam', 'exam__course').order_by('-assigned_at')
    for exam_assignment in exam_assignments:
        exam_assignments_by_student.setdefault(exam_assignment.student_id, []).append(exam_assignment)

    session_summary_by_student = {}
    session_summaries = QuizSession.objects.filter(
        student_id__in=assigned_student_ids
    ).exclude(status='ongoing').values('student_id').annotate(
        completed_count=Count('id'),
        review_count=Count('id', filter=Q(is_reviewed=False)),
        flagged_count=Count('id', filter=Q(status='flagged')),
    )
    for summary in session_summaries:
        session_summary_by_student[summary['student_id']] = summary

    for assignment in assignments:
        student_exam_assignments = exam_assignments_by_student.get(assignment.student_id, [])
        summary = session_summary_by_student.get(assignment.student_id, {})
        assignment.assigned_exams = student_exam_assignments
        assignment.assigned_exam_count = len(student_exam_assignments)
        assignment.submitted_exam_count = sum(1 for item in student_exam_assignments if item.status == 'submitted')
        assignment.completed_exam_count = sum(1 for item in student_exam_assignments if item.status == 'completed')
        assignment.completed_session_count = summary.get('completed_count', 0)
        assignment.review_session_count = summary.get('review_count', 0)
        assignment.flagged_session_count = summary.get('flagged_count', 0)

    # Exams for the dashboard
    exams = Exam.objects.filter(created_by=teacher).prefetch_related('questions', 'assignments')
    
    return render(request, 'teachers/teacher_dashboard.html', {
        'assignments': assignments,
        'total_students': assignments.values_list('student_id', flat=True).distinct().count(),
        'all_subjects': all_subjects,
        'videos': videos,
        'recent_sessions': recent_sessions,
        'review_count': review_count,
        'flagged_count': flagged_count,

        'exams': exams
    })


@login_required
@user_passes_test(is_teacher)
def delete_student_assignment(request, student_id):
    # This just removes the assignment from this teacher, NOT the student user account
    assignment = TeacherStudentAssignment.objects.filter(teacher=request.user, student_id=student_id).first()
    if assignment:
        student_name = assignment.student.username
        assignment.delete()
        messages.success(request, f"Student {student_name} removed from your roster.")
    return redirect('/teachers/dashboard/#students')


@login_required
@user_passes_test(is_teacher)
def student_exam_status(request, student_id):
    assignment = get_object_or_404(
        TeacherStudentAssignment.objects.select_related('student', 'course'),
        teacher=request.user,
        student_id=student_id,
    )
    student = assignment.student

    exam_assignments = ExamAssignment.objects.filter(
        student=student,
        exam__created_by=request.user,
    ).select_related('exam', 'exam__course').order_by('-assigned_at')

    sessions_by_exam_id = {}
    sessions = QuizSession.objects.filter(
        student=student,
        exam_id__in=exam_assignments.values_list('exam_id', flat=True),
    ).select_related('exam').order_by('exam_id', '-start_time')
    for session in sessions:
        sessions_by_exam_id.setdefault(session.exam_id, session)

    totals = {
        'assigned': 0,
        'not_started': 0,
        'submitted': 0,
        'completed': 0,
        'flagged': 0,
    }

    for exam_assignment in exam_assignments:
        session = sessions_by_exam_id.get(exam_assignment.exam_id)
        exam_assignment.latest_session = session
        totals['assigned'] += 1
        exam_assignment.score_display = None
        if exam_assignment.final_score is not None:
            exam_assignment.score_display = exam_assignment.final_score
        elif session and session.is_reviewed and session.score is not None:
            exam_assignment.score_display = session.score

        if exam_assignment.status == 'completed':
            totals['completed'] += 1
            exam_assignment.status_label = 'Published'
            exam_assignment.status_class = 'success'
            exam_assignment.condition_label = 'Final mark published'
            exam_assignment.condition_class = 'success'
        elif exam_assignment.status == 'submitted':
            totals['submitted'] += 1
            exam_assignment.status_label = 'Waiting Review'
            exam_assignment.status_class = 'warning'
            exam_assignment.condition_label = 'Student submitted, teacher grading pending'
            exam_assignment.condition_class = 'warning'
        else:
            totals['not_started'] += 1
            exam_assignment.status_label = 'Assigned'
            exam_assignment.status_class = 'primary'
            exam_assignment.condition_label = 'Not submitted yet'
            exam_assignment.condition_class = 'secondary'

        if session and session.status == 'ongoing':
            exam_assignment.condition_label = 'Live exam in progress'
            exam_assignment.condition_class = 'info'
        elif session and session.status == 'flagged':
            totals['flagged'] += 1
            exam_assignment.condition_label = 'Integrity flagged'
            exam_assignment.condition_class = 'danger'
        elif session and session.status == 'disqualified':
            exam_assignment.condition_label = 'Disqualified'
            exam_assignment.condition_class = 'dark'

    return render(request, 'teachers/student_exam_status.html', {
        'assignment': assignment,
        'student': student,
        'exam_assignments': exam_assignments,
        'available_exams': Exam.objects.filter(created_by=request.user).select_related('course').order_by('-created_at'),
        'totals': totals,
    })


@login_required
@user_passes_test(is_teacher)
def assign_or_reexam_student(request, student_id):
    if request.method != 'POST':
        return redirect('student_exam_status', student_id=student_id)

    teacher_assignment = get_object_or_404(
        TeacherStudentAssignment.objects.select_related('student'),
        teacher=request.user,
        student_id=student_id,
    )
    exam = get_object_or_404(Exam, id=request.POST.get('exam_id'), created_by=request.user)
    exam_assignment, created = ExamAssignment.objects.get_or_create(
        exam=exam,
        student=teacher_assignment.student,
        defaults={'status': 'assigned'},
    )

    QuizSession.objects.filter(student=teacher_assignment.student, exam=exam).delete()
    if not created:
        exam_assignment.status = 'assigned'
        exam_assignment.final_score = None
        exam_assignment.due_date = None
        exam_assignment.save(update_fields=['status', 'final_score', 'due_date'])

    student_name = teacher_assignment.student.get_full_name() or teacher_assignment.student.username
    action = 'assigned' if created else 'reset for re-exam'
    messages.success(request, f"'{exam.title}' {action} for {student_name}.")
    return redirect('student_exam_status', student_id=student_id)


@login_required
@user_passes_test(is_teacher)
def cancel_student_exam_assignment(request, student_id, assignment_id):
    if request.method != 'POST':
        return redirect('student_exam_status', student_id=student_id)

    get_object_or_404(
        TeacherStudentAssignment,
        teacher=request.user,
        student_id=student_id,
    )
    exam_assignment = get_object_or_404(
        ExamAssignment.objects.select_related('exam', 'student'),
        id=assignment_id,
        student_id=student_id,
        exam__created_by=request.user,
    )
    exam_title = exam_assignment.exam.title
    student_name = exam_assignment.student.get_full_name() or exam_assignment.student.username

    QuizSession.objects.filter(
        student_id=student_id,
        exam=exam_assignment.exam,
    ).delete()
    exam_assignment.delete()

    messages.success(request, f"Removed '{exam_title}' from {student_name}.")
    return redirect('student_exam_status', student_id=student_id)


@login_required
@user_passes_test(is_teacher)
def teacher_manage_exam(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    # ensure teacher is assigned to course
    allowed = TeacherStudentAssignment.objects.filter(teacher=request.user, course=video.course).exists()
    if not allowed:
        messages.error(request, "You are not assigned to this lesson.")
        return redirect('teacher_dashboard')

    if request.method == 'POST':
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.video = video
            quiz.save()
            messages.success(request, "Question added.")
            return redirect('teacher_manage_exam', video_id=video.id)
    else:
        form = QuizForm()

    questions = video.questions.all()
    return render(request, 'add_quiz.html', {
        'form': form,
        'video': video,
        'questions': questions,
        'back_url': 'teacher_dashboard',
        'is_teacher': True
    })


def is_admin(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(is_admin)
def create_teacher(request):
    if request.method == 'POST':
        form = TeacherCreateForm(request.POST)
        if form.is_valid():
            teacher = form.save()
            messages.success(request, f"Teacher {teacher.username} created.")
            return redirect('create_teacher')
    else:
        form = TeacherCreateForm()
    return render(request, 'teachers/create_teacher.html', {'form': form})


@login_required
@user_passes_test(is_admin)
def assign_teacher(request):
    if request.method == 'POST':
        form = TeacherStudentAssignmentForm(request.POST)
        if form.is_valid():
            assignment, created = TeacherStudentAssignment.objects.get_or_create(
                teacher=form.cleaned_data['teacher'],
                student=form.cleaned_data['student'],
                course=form.cleaned_data['course'],
            )
            if created:
                messages.success(request, "Assignment created.")
            else:
                messages.info(request, "Assignment already exists.")
            return redirect('assign_teacher')
    else:
        form = TeacherStudentAssignmentForm()
    assignments = TeacherStudentAssignment.objects.select_related('teacher', 'student', 'course').order_by('-created_at')
    return render(request, 'teachers/assign_teacher.html', {'form': form, 'assignments': assignments})


@login_required
@user_passes_test(is_teacher)
def create_student(request):
    from .forms import StudentCreateForm
    from examiners.models import ExaminerTeacherAssignment
    
    examiner_assignment = ExaminerTeacherAssignment.objects.filter(teacher=request.user).first()
    if examiner_assignment:
        allowed_subjects = Course.objects.filter(
            Q(created_by=examiner_assignment.examiner) | Q(created_by__isnull=True)
        ).order_by('-created_at')
    else:
        allowed_subjects = Course.objects.filter(created_by__isnull=True).order_by('-created_at')
        
    if request.method == 'POST':
        form = StudentCreateForm(request.POST)
        form.fields['course'].queryset = allowed_subjects
        if form.is_valid():
            student = form.save()
            course = form.cleaned_data.get('course')
            if course:
                TeacherStudentAssignment.objects.create(teacher=request.user, student=student, course=course)
            messages.success(request, f"Student {student.username} created.")
            return redirect('teacher_dashboard')
    else:
        form = StudentCreateForm()
        form.fields['course'].queryset = allowed_subjects
    return render(request, 'teachers/create_student.html', {'form': form})


@login_required
@user_passes_test(is_teacher)
def teacher_proctoring_dashboard(request):
    # Show only sessions for the students assigned to this teacher
    assigned_students = TeacherStudentAssignment.objects.filter(teacher=request.user).values_list('student', flat=True)
    sessions = QuizSession.objects.filter(student__in=assigned_students).prefetch_related('proctoring_logs').order_by('-start_time')
    for session in sessions:
        session.risk_report = calculate_risk_report(session.proctoring_logs.all())
    return render(request, 'teachers/teacher_proctoring_dashboard.html', {'sessions': sessions})


@login_required
@user_passes_test(is_teacher)
def teacher_review_exam(request, session_id):
    from courses.models import Enrollment, Progress
    from django.utils import timezone
    session = get_object_or_404(QuizSession, id=session_id)
    logs = session.proctoring_logs.all().order_by('timestamp')
    risk_report = calculate_risk_report(logs)

    # Ensure teacher manages this student
    if not TeacherStudentAssignment.objects.filter(teacher=request.user, student=session.student).exists():
        messages.error(request, "You are not authorized to review this student's exams.")
        return redirect('teacher_proctoring_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')
        admin_notes = request.POST.get('admin_notes', '')

        session.admin_notes = admin_notes
        session.is_reviewed = True

        if action == 'approve':
            session.status = 'submitted'
            if session.score is not None and session.score >= 75:
                enrollment = Enrollment.objects.filter(student=session.student, course=session.video.course).first()
                if enrollment:
                    progress, created = Progress.objects.get_or_create(student=session.student, video=session.video, defaults={'passed': True})
                    if not progress.passed:
                        progress.passed = True
                        progress.save()
                    if enrollment.current_lesson_index <= session.video.order:
                        enrollment.current_lesson_index = min(session.video.order + 1, session.video.course.videos.count())
                    total_videos = session.video.course.videos.count()
                    passed_videos = Progress.objects.filter(student=session.student, video__course=session.video.course, passed=True).count()
                    if passed_videos >= total_videos and not enrollment.is_completed:
                        enrollment.is_completed = True
                        enrollment.completed_at = timezone.now()
                    enrollment.save()
            messages.success(request, f"Session approved for {session.student.username}.")
        elif action == 'disqualify':
            session.status = 'disqualified'
            messages.error(request, f"Student {session.student.username} has been disqualified.")
        elif action == 'allow_retake':
            session.allow_retake = True
            session.status = 'submitted'
            session.end_time = None
            session.is_reviewed = False
            session.score = None
            session.proctoring_logs.all().delete()
            messages.info(request, f"Retake unlocked for {session.student.username}.")
        
        session.save()
        return redirect('teacher_proctoring_dashboard')

    return render(request, 'review_quiz_session.html', {
        'session': session,
        'logs': logs,
        'risk_report': risk_report,
        'is_teacher': True,
        'back_url': 'teacher_proctoring_dashboard'
    })

@login_required
@user_passes_test(is_teacher)
def delete_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id, created_by=request.user)
    title = exam.title
    exam.delete()
    messages.success(request, f"Exam Paper '{title}' deleted.")
    return redirect('/teachers/dashboard/#exams')

@login_required
@user_passes_test(is_teacher)
def teacher_exam_questions(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id, created_by=request.user)
    
    if request.method == 'POST':
        q_type = request.POST.get('q_type', 'mcq')
        question_text = request.POST.get('question')
        opt1 = request.POST.get('option_1', '')
        opt2 = request.POST.get('option_2', '')
        opt3 = request.POST.get('option_3', '')
        opt4 = request.POST.get('option_4', '')
        points = request.POST.get('points', 1.0)
        
        # Handle Correct Answer based on type
        if q_type == 'mcq':
            correct_answer = request.POST.get('correct_option', '')
        elif q_type == 'multi':
            correct_list = request.POST.getlist('correct_options')
            correct_answer = ",".join(correct_list)
        else: # essay
            correct_answer = ""
            opt1 = opt2 = opt3 = opt4 = ""

        # Validation: MCQ and Multi-Select MUST have a correct answer defined
        if q_type != 'essay' and not correct_answer:
            messages.error(request, f"Please select at least one correct answer for your {q_type.upper()} question.")
            return redirect('teacher_exam_questions', exam_id=exam.id)

        ExamQuestion.objects.create(
            exam=exam,
            q_type=q_type,
            question=question_text,
            option_1=opt1,
            option_2=opt2,
            option_3=opt3,
            option_4=opt4,
            correct_answer=correct_answer,
            points=points
        )
        messages.success(request, f"{q_type.upper()} question added successfully.")
        return redirect('teacher_exam_questions', exam_id=exam.id)

    questions = exam.questions.all()
    return render(request, 'teachers/add_exam_quiz.html', {
        'exam': exam,
        'questions': questions,
        'back_url': 'teacher_dashboard'
    })

@login_required
@user_passes_test(is_teacher)
def delete_exam_question(request, question_id):
    question = get_object_or_404(ExamQuestion, id=question_id, exam__created_by=request.user)
    exam_id = question.exam.id
    question.delete()
    messages.success(request, "Question removed from exam paper.")
    return redirect('teacher_exam_questions', exam_id=exam_id)

@login_required
@user_passes_test(is_teacher)
def grade_exam_session(request, session_id):
    session = get_object_or_404(QuizSession, id=session_id, exam__created_by=request.user)
    
    if request.method == 'POST':
        # Update essay marks
        for key, value in request.POST.items():
            if key.startswith('marks_'):
                answer_id = key.split('_')[1]
                try:
                    marks = float(value or 0)
                except (TypeError, ValueError):
                    marks = 0
                ans = StudentAnswer.objects.get(id=answer_id, session=session)
                marks = max(0, min(marks, ans.question.points))
                ans.marks_earned = marks
                ans.is_correct = marks > (ans.question.points / 2) # Arbitrary threshold
                ans.save()
        
        # Re-calculate total score
        total_earned = sum(ans.marks_earned for ans in session.answers.all())
        max_possible = sum(q.points for q in session.exam.questions.all())
        percentage = (total_earned / max_possible * 100) if max_possible > 0 else 0
        
        session.score = percentage
        session.status = 'submitted' # Keep as submitted but marked as reviewed
        session.is_reviewed = True
        session.admin_notes = request.POST.get('admin_notes')
        session.save()
        
        # Update assignment as well
        assignment = ExamAssignment.objects.filter(exam=session.exam, student=session.student).first()
        if assignment:
            assignment.final_score = percentage
            assignment.status = 'completed'
            assignment.save()
            
        messages.success(request, f"Grading completed for {session.student.username}. Final Score: {int(percentage)}%")
        return redirect('teacher_proctoring_dashboard')

    answers = session.answers.select_related('question').all()
    logs = session.proctoring_logs.all().order_by('-timestamp')
    risk_report = calculate_risk_report(logs)
    
    return render(request, 'teachers/grade_exam_session.html', {
        'session': session,
        'answers': answers,
        'logs': logs,
        'risk_report': risk_report,
    })
