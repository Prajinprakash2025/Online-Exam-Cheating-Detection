import random
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from .forms import ExaminerSignupForm, ExaminerStudentCreateForm, SubjectForm
from teachers.forms import TeacherCreateForm
from teachers.models import TeacherStudentAssignment
from courses.models import Course, QuizSession, ProctoringLog, Exam, ExamQuestion, ExamAssignment
from .models import ExaminerTeacherAssignment

User = get_user_model()

EXAMINER_LOGIN_OTP_MINUTES = 10
EXAMINER_SIGNUP_OTP_MINUTES = 10


def _clear_examiner_login_otp(request):
    for key in (
        'examiner_login_user_id',
        'examiner_login_email',
        'examiner_login_otp',
        'examiner_login_otp_expires_at',
    ):
        request.session.pop(key, None)


def _clear_examiner_signup_otp(request):
    for key in (
        'examiner_signup_data',
        'examiner_signup_email',
        'examiner_signup_otp',
        'examiner_signup_otp_expires_at',
    ):
        request.session.pop(key, None)


def _print_examiner_otp(purpose, email, otp):
    print("\n" + "=" * 64)
    print(f"ExamGate {purpose} OTP for {email}: {otp}")
    print("=" * 64 + "\n")


def _send_examiner_otp(email, subject, message, otp, purpose):
    _print_examiner_otp(purpose, email, otp)

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


def _examiner_otp_context(request):
    expires_at = request.session.get('examiner_login_otp_expires_at')
    otp_email = request.session.get('examiner_login_email')

    if not expires_at or not otp_email:
        return {'otp_sent': False}

    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        _clear_examiner_login_otp(request)
        return {'otp_sent': False}

    if timezone.now().timestamp() > expires_at:
        _clear_examiner_login_otp(request)
        return {'otp_sent': False}

    return {'otp_sent': True, 'otp_email': otp_email}


def _examiner_signup_context(request, form=None):
    pending_data = request.session.get('examiner_signup_data') or {}
    expires_at = request.session.get('examiner_signup_otp_expires_at')
    otp_email = request.session.get('examiner_signup_email')

    if form is None:
        form = ExaminerSignupForm(initial=pending_data)

    if not expires_at or not otp_email:
        return {'form': form, 'otp_sent': False}

    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        _clear_examiner_signup_otp(request)
        return {'form': form, 'otp_sent': False}

    if timezone.now().timestamp() > expires_at:
        _clear_examiner_signup_otp(request)
        return {'form': form, 'otp_sent': False}

    return {'form': form, 'otp_sent': True, 'otp_email': otp_email}


def examiner_signup(request):
    if request.GET.get('reset') == '1':
        _clear_examiner_signup_otp(request)
        return redirect('examiner_signup')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'verify_signup_otp':
            entered_otp = (request.POST.get('otp') or '').strip()
            saved_otp = str(request.session.get('examiner_signup_otp') or '')
            expires_at = request.session.get('examiner_signup_otp_expires_at')
            pending_data = request.session.get('examiner_signup_data') or {}

            if not pending_data or not saved_otp or not expires_at:
                messages.error(request, "Please request a fresh signup OTP.")
                return redirect('examiner_signup')

            try:
                expires_at = float(expires_at)
            except (TypeError, ValueError):
                _clear_examiner_signup_otp(request)
                messages.error(request, "Please request a fresh signup OTP.")
                return redirect('examiner_signup')

            if timezone.now().timestamp() > expires_at:
                _clear_examiner_signup_otp(request)
                messages.error(request, "Your signup OTP expired. Please request a new one.")
                return redirect('examiner_signup')

            if entered_otp != saved_otp:
                messages.error(request, "Invalid OTP. Please try again.")
                return render(request, 'examiners/examiner_signup.html', _examiner_signup_context(request))

            form = ExaminerSignupForm(pending_data)
            if not form.is_valid():
                _clear_examiner_signup_otp(request)
                messages.error(request, "Please submit the conductor details again.")
                return render(request, 'examiners/examiner_signup.html', {'form': form, 'otp_sent': False})

            user = form.save()
            _clear_examiner_signup_otp(request)
            login(request, user)
            messages.success(request, "Conductor account verified and created successfully. Welcome to the Master Hub!")
            return redirect('examiner_dashboard')

        form = ExaminerSignupForm(request.POST)
        if form.is_valid():
            otp = f"{random.randint(100000, 999999)}"
            email = form.cleaned_data['email']
            pending_data = {
                'email': email,
                'first_name': form.cleaned_data.get('first_name') or '',
                'last_name': form.cleaned_data.get('last_name') or '',
            }
            subject = 'Your ExamGate Conductor Signup OTP'
            message = (
                f"Hello {pending_data['first_name'] or 'Conductor'},\n\n"
                f"Your ExamGate conductor signup OTP is: {otp}\n\n"
                f"This code is valid for {EXAMINER_SIGNUP_OTP_MINUTES} minutes."
            )

            _send_examiner_otp(email, subject, message, otp, 'conductor signup')

            request.session['examiner_signup_data'] = pending_data
            request.session['examiner_signup_email'] = email
            request.session['examiner_signup_otp'] = otp
            request.session['examiner_signup_otp_expires_at'] = (
                timezone.now() + timedelta(minutes=EXAMINER_SIGNUP_OTP_MINUTES)
            ).timestamp()

            messages.success(request, f"OTP generated for {email}. Check your terminal for the code.")
            return render(request, 'examiners/examiner_signup.html', _examiner_signup_context(request, ExaminerSignupForm(initial=pending_data)))
    else:
        return render(request, 'examiners/examiner_signup.html', _examiner_signup_context(request))

    return render(request, 'examiners/examiner_signup.html', {'form': form, 'otp_sent': False})


def examiner_login(request):
    if request.GET.get('reset') == '1':
        _clear_examiner_login_otp(request)
        return redirect('examiner_login')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'verify_otp':
            entered_otp = (request.POST.get('otp') or '').strip()
            saved_otp = str(request.session.get('examiner_login_otp') or '')
            user_id = request.session.get('examiner_login_user_id')
            expires_at = request.session.get('examiner_login_otp_expires_at')

            if not user_id or not saved_otp or not expires_at:
                messages.error(request, "Please request a fresh login OTP.")
                return redirect('examiner_login')

            try:
                expires_at = float(expires_at)
            except (TypeError, ValueError):
                _clear_examiner_login_otp(request)
                messages.error(request, "Please request a fresh login OTP.")
                return redirect('examiner_login')

            if timezone.now().timestamp() > expires_at:
                _clear_examiner_login_otp(request)
                messages.error(request, "Your login OTP expired. Please request a new one.")
                return redirect('examiner_login')

            if entered_otp != saved_otp:
                messages.error(request, "Invalid OTP. Please try again.")
                return render(request, 'examiners/examiner_login.html', _examiner_otp_context(request))

            user = get_object_or_404(User, id=user_id, is_examiner=True)
            login(request, user)
            _clear_examiner_login_otp(request)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect('examiner_dashboard')

        email = (request.POST.get('email') or '').strip().lower()
        user = User.objects.filter(email__iexact=email, is_examiner=True).first()

        if not user:
            messages.error(request, "No master conductor account was found for that email.")
            return render(request, 'examiners/examiner_login.html', {'otp_sent': False})

        otp = f"{random.randint(100000, 999999)}"
        subject = 'Your ExamGate Master Conductor OTP'
        message = (
            f"Hello {user.first_name or user.username},\n\n"
            f"Your ExamGate login OTP is: {otp}\n\n"
            f"This code is valid for {EXAMINER_LOGIN_OTP_MINUTES} minutes."
        )

        try:
            _send_examiner_otp(user.email, subject, message, otp, 'conductor login')
        except Exception as exc:
            messages.error(request, f"Could not send OTP email: {exc}")
            return render(request, 'examiners/examiner_login.html', {'otp_sent': False})

        request.session['examiner_login_user_id'] = user.id
        request.session['examiner_login_email'] = user.email
        request.session['examiner_login_otp'] = otp
        request.session['examiner_login_otp_expires_at'] = (
            timezone.now() + timedelta(minutes=EXAMINER_LOGIN_OTP_MINUTES)
        ).timestamp()

        messages.success(request, f"OTP generated for {user.email}. Check your terminal for the code.")
        return render(request, 'examiners/examiner_login.html', _examiner_otp_context(request))

    return render(request, 'examiners/examiner_login.html', _examiner_otp_context(request))


@login_required
def examiner_logout(request):
    logout(request)
    return redirect('examiner_login')


def is_examiner(user):
    return user.is_authenticated and user.is_examiner


def _first_form_error(form):
    for _field, errors in form.errors.items():
        if errors:
            return errors[0]
    return "Please check the form and try again."


@login_required
@user_passes_test(is_examiner)
def examiner_dashboard(request):
    examiner = request.user
    assignments = ExaminerTeacherAssignment.objects.filter(examiner=examiner).select_related('teacher')
    teachers = [a.teacher for a in assignments]
    teacher_ids = [t.id for t in teachers]
    managed_student_assignments = TeacherStudentAssignment.objects.filter(
        teacher_id__in=teacher_ids
    ).select_related('teacher', 'student', 'course')
    managed_student_ids = [a.student_id for a in managed_student_assignments]
    
    # Handle POST for Registration
    teacher_form = TeacherCreateForm()
    candidate_form = ExaminerStudentCreateForm(examiner=examiner)
    subject_form = SubjectForm()
    active_modal = None
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'register_conductor':
            teacher_form = TeacherCreateForm(request.POST)
            if teacher_form.is_valid():
                teacher = teacher_form.save()
                ExaminerTeacherAssignment.objects.create(examiner=examiner, teacher=teacher)
                messages.success(request, f"Teacher {teacher.username} registered successfully.")
                return redirect('/examiners/dashboard/#teachers')
            active_modal = 'registerTeacherModal'
            messages.error(request, f"Could not create teacher: {_first_form_error(teacher_form)}")
        
        elif action == 'register_candidate':
            candidate_form = ExaminerStudentCreateForm(request.POST, examiner=examiner)
            if candidate_form.is_valid():
                candidate = candidate_form.save()
                messages.success(request, f"Candidate {candidate.username} registered and assigned.")
                return redirect('/examiners/dashboard/#candidates')
            active_modal = 'registerCandidateModal'
            messages.error(request, f"Could not create candidate: {_first_form_error(candidate_form)}")
        
        elif action == 'register_subject':
            subject_form = SubjectForm(request.POST, request.FILES)
            if subject_form.is_valid():
                subject = subject_form.save()
                messages.success(request, f"New exam subject '{subject.title}' created.")
                return redirect('/examiners/dashboard/#subjects')

        elif action == 'create_exam':
            title = (request.POST.get('title') or '').strip()
            course_id = request.POST.get('course')
            duration = request.POST.get('duration') or 60
            passing_score = request.POST.get('passing_score') or 50
            description = request.POST.get('description', '')

            if not title:
                messages.error(request, "Please enter an exam title.")
                return redirect('/examiners/dashboard/#exams')
            if not course_id:
                messages.error(request, "Please create or select a subject before creating an exam.")
                return redirect('/examiners/dashboard/#exams')

            course = get_object_or_404(Course, id=course_id)
            exam = Exam.objects.create(
                title=title,
                course=course,
                duration_minutes=duration,
                passing_score=passing_score,
                description=description,
                created_by=examiner,
            )
            messages.success(request, f"Exam Paper '{title}' designed. Now add your questions.")
            return redirect('examiner_exam_questions', exam_id=exam.id)

        elif action == 'assign_exam':
            exam_id = request.POST.get('exam_id')
            raw_student_ids = request.POST.get('student_ids', '')
            if ',' in raw_student_ids:
                student_ids = [sid.strip() for sid in raw_student_ids.split(',') if sid.strip()]
            else:
                student_ids = request.POST.getlist('student_ids')

            exam = get_object_or_404(Exam, id=exam_id, created_by=examiner)
            allowed_student_ids = set(str(student_id) for student_id in managed_student_ids)

            count = 0
            for student_id in student_ids:
                if student_id not in allowed_student_ids:
                    continue
                student = get_object_or_404(User, id=student_id, is_student=True)
                _, created = ExamAssignment.objects.get_or_create(exam=exam, student=student)
                if created:
                    count += 1

            messages.success(request, f"Successfully assigned '{exam.title}' to {count} candidates.")
            return redirect('/examiners/dashboard/#candidates')
        
        elif action == 'edit_subject':
            subject_id = request.POST.get('subject_id')
            subject = get_object_or_404(Course, id=subject_id)
            subject_form = SubjectForm(request.POST, request.FILES, instance=subject)
            if subject_form.is_valid():
                subject_form.save()
                messages.success(request, f"Subject '{subject.title}' updated successfully.")
                return redirect('/examiners/dashboard/#subjects')

        elif action == 'edit_exam':
            exam_id = request.POST.get('exam_id')
            exam = get_object_or_404(Exam, id=exam_id, created_by=examiner)
            exam.title = request.POST.get('title', exam.title)
            exam.duration_minutes = request.POST.get('duration', exam.duration_minutes)
            exam.passing_score = request.POST.get('passing_score', exam.passing_score)
            exam.description = request.POST.get('description', exam.description)
            exam.save()
            messages.success(request, f"Exam '{exam.title}' updated.")
            return redirect('/examiners/dashboard/#exams')

        elif action == 'edit_conductor':
            conductor_id = request.POST.get('conductor_id')
            conductor = get_object_or_404(User, id=conductor_id, is_teacher=True)
            conductor.first_name = request.POST.get('first_name', conductor.first_name)
            conductor.last_name = request.POST.get('last_name', conductor.last_name)
            conductor.email = request.POST.get('email', conductor.email)
            conductor.save()
            messages.success(request, f"Conductor {conductor.username} updated.")
            return redirect('/examiners/dashboard/#teachers')

        elif action == 'edit_candidate':
            candidate_id = request.POST.get('candidate_id')
            candidate = get_object_or_404(User, id=candidate_id, is_student=True)
            candidate.first_name = request.POST.get('first_name', candidate.first_name)
            candidate.last_name = request.POST.get('last_name', candidate.last_name)
            candidate.email = request.POST.get('email', candidate.email)
            candidate.save()
            messages.success(request, f"Candidate {candidate.username} updated.")
            return redirect('/examiners/dashboard/#candidates')

    # Aggregated Stats
    total_candidates = len(set(managed_student_ids))
    recent_sessions = QuizSession.objects.filter(
        student_id__in=managed_student_ids
    ).exclude(status='ongoing').select_related('student', 'video__course').order_by('-start_time')[:10]
    
    flagged_sessions_count = QuizSession.objects.filter(
        student_id__in=managed_student_ids,
        status='flagged'
    ).count()
    review_count = QuizSession.objects.filter(
        student_id__in=managed_student_ids,
    ).exclude(status='ongoing').filter(is_reviewed=False).count()

    exam_assignments_by_student = {}
    exam_assignments = ExamAssignment.objects.filter(
        student_id__in=managed_student_ids,
        exam__created_by=examiner,
    ).select_related('exam', 'exam__course').order_by('-assigned_at')
    for exam_assignment in exam_assignments:
        exam_assignments_by_student.setdefault(exam_assignment.student_id, []).append(exam_assignment)

    session_summary_by_student = {}
    session_summaries = QuizSession.objects.filter(
        student_id__in=managed_student_ids
    ).exclude(status='ongoing').values('student_id').annotate(
        completed_count=Count('id'),
        review_count=Count('id', filter=Q(is_reviewed=False)),
        flagged_count=Count('id', filter=Q(status='flagged')),
    )
    for summary in session_summaries:
        session_summary_by_student[summary['student_id']] = summary

    for assignment in managed_student_assignments:
        student_exam_assignments = exam_assignments_by_student.get(assignment.student_id, [])
        summary = session_summary_by_student.get(assignment.student_id, {})
        assignment.assigned_exams = student_exam_assignments
        assignment.assigned_exam_count = len(student_exam_assignments)
        assignment.submitted_exam_count = sum(1 for item in student_exam_assignments if item.status == 'submitted')
        assignment.completed_exam_count = sum(1 for item in student_exam_assignments if item.status == 'completed')
        assignment.completed_session_count = summary.get('completed_count', 0)
        assignment.review_session_count = summary.get('review_count', 0)
        assignment.flagged_session_count = summary.get('flagged_count', 0)

    return render(request, 'examiners/examiner_dashboard.html', {
        'teachers': teachers,
        'candidates': managed_student_assignments,
        'all_subjects': Course.objects.all().order_by('-created_at'),
        'exams': Exam.objects.filter(created_by=examiner).prefetch_related('questions', 'assignments'),
        'total_teachers': len(teachers),
        'total_candidates': total_candidates,
        'flagged_count': flagged_sessions_count,
        'review_count': review_count,
        'recent_sessions': recent_sessions,
        'teacher_form': teacher_form,
        'candidate_form': candidate_form,
        'subject_form': subject_form,
        'active_modal': active_modal,
    })


@login_required
@user_passes_test(is_examiner)
def delete_conductor(request, teacher_id):
    assignment = ExaminerTeacherAssignment.objects.filter(examiner=request.user, teacher_id=teacher_id).first()
    if assignment:
        teacher_name = assignment.teacher.username
        assignment.delete()
        messages.success(request, f"Conductor {teacher_name} removed from your management.")
    return redirect('examiner_dashboard')


@login_required
@user_passes_test(is_examiner)
def delete_candidate(request, student_id):
    # Find assignments of this candidate under any of this examiner's teachers
    examiner_teacher_ids = ExaminerTeacherAssignment.objects.filter(
        examiner=request.user
    ).values_list('teacher_id', flat=True)
    
    assignment = TeacherStudentAssignment.objects.filter(
        teacher_id__in=examiner_teacher_ids, 
        student_id=student_id
    ).first()
    
    if assignment:
        student_name = assignment.student.username
        assignment.delete()
        messages.success(request, f"Candidate {student_name} removed from your managed list.")
    return redirect('examiner_dashboard')


@login_required
@user_passes_test(is_examiner)
def delete_subject(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    title = course.title
    course.delete()
    messages.success(request, f"Exam subject '{title}' has been deleted.")
    return redirect('examiner_dashboard')


@login_required
@user_passes_test(is_examiner)
def delete_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id, created_by=request.user)
    title = exam.title
    exam.delete()
    messages.success(request, f"Exam Paper '{title}' deleted.")
    return redirect('/examiners/dashboard/#exams')


@login_required
@user_passes_test(is_examiner)
def examiner_exam_questions(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id, created_by=request.user)

    if request.method == 'POST':
        q_type = request.POST.get('q_type', 'mcq')
        question_text = request.POST.get('question')
        opt1 = request.POST.get('option_1', '')
        opt2 = request.POST.get('option_2', '')
        opt3 = request.POST.get('option_3', '')
        opt4 = request.POST.get('option_4', '')
        points = request.POST.get('points', 1.0)

        if q_type == 'mcq':
            correct_answer = request.POST.get('correct_option', '')
        elif q_type == 'multi':
            correct_answer = ",".join(request.POST.getlist('correct_options'))
        else:
            correct_answer = ""
            opt1 = opt2 = opt3 = opt4 = ""

        if q_type != 'essay' and not correct_answer:
            messages.error(request, f"Please select at least one correct answer for your {q_type.upper()} question.")
            return redirect('examiner_exam_questions', exam_id=exam.id)

        ExamQuestion.objects.create(
            exam=exam,
            q_type=q_type,
            question=question_text,
            option_1=opt1,
            option_2=opt2,
            option_3=opt3,
            option_4=opt4,
            correct_answer=correct_answer,
            points=points,
        )
        messages.success(request, f"{q_type.upper()} question added successfully.")
        return redirect('examiner_exam_questions', exam_id=exam.id)

    return render(request, 'teachers/add_exam_quiz.html', {
        'exam': exam,
        'questions': exam.questions.all(),
        'back_dashboard_url': '/examiners/dashboard/#exams',
        'delete_question_url_name': 'examiner_delete_exam_question',
    })


@login_required
@user_passes_test(is_examiner)
def delete_exam_question(request, question_id):
    question = get_object_or_404(ExamQuestion, id=question_id, exam__created_by=request.user)
    exam_id = question.exam.id
    question.delete()
    messages.success(request, "Question removed from exam paper.")
    return redirect('examiner_exam_questions', exam_id=exam_id)


@login_required
@user_passes_test(is_examiner)
def create_teacher(request):
    if request.method == 'POST':
        form = TeacherCreateForm(request.POST)
        if form.is_valid():
            teacher = form.save()
            ExaminerTeacherAssignment.objects.create(examiner=request.user, teacher=teacher)
            messages.success(request, f"Teacher {teacher.username} created successfully.")
            return redirect('examiner_dashboard')
    else:
        form = TeacherCreateForm()
    return render(request, 'examiners/create_teacher.html', {'form': form})
