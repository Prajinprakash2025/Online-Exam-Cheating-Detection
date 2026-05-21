from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Count, Q
from courses.models import Course, Video, Quiz, QuizSession, Exam, ExamQuestion, ExamAssignment, StudentAnswer
from courses.forms import QuizForm
from courses.proctoring import calculate_risk_report
from examiners.forms import SubjectForm
from .models import TeacherStudentAssignment
from .forms import StudentCreateForm


def teacher_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        # We use email as the username field in our custom User model
        user = authenticate(request, username=email, password=password)
        if user and user.is_teacher:
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect('teacher_dashboard')
        messages.error(request, "Invalid conductor credentials. Please check your email and password.")
    return render(request, 'teachers/teacher_login.html')


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
    # Handle Subject Registration
    subject_form = SubjectForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'register_subject':
            subject_form = SubjectForm(request.POST, request.FILES)
            if subject_form.is_valid():
                subject = subject_form.save()
                messages.success(request, f"New exam subject '{subject.title}' created.")
                return redirect('/teachers/dashboard/#subjects')

        elif action == 'edit_subject':
            subject_id = request.POST.get('subject_id')
            subject = get_object_or_404(Course, id=subject_id)
            form = SubjectForm(request.POST, request.FILES, instance=subject)
            if form.is_valid():
                form.save()
                messages.success(request, f"Subject '{subject.title}' updated successfully.")
                return redirect('/teachers/dashboard/#subjects')

        elif action == 'register_student':
            from courses.models import User
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            email = request.POST.get('email')
            password = request.POST.get('password')
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
                # Create new user
                student = User.objects.create_user(
                    username=email, 
                    email=email, 
                    password=password, 
                    first_name=first_name, 
                    last_name=last_name,
                    is_student=True
                )
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
    
    # All courses (or maybe just those relevant to teacher - user said "conductor can add the subject")
    all_subjects = Course.objects.all().order_by('-created_at')
    
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
        'subject_form': subject_form,
        'exams': exams
    })


@login_required
@user_passes_test(is_teacher)
def delete_teacher_subject(request, course_id):
    # For now, allow teachers to delete subjects (as requested "conductor add section also add crud")
    course = get_object_or_404(Course, id=course_id)
    title = course.title
    course.delete()
    messages.success(request, f"Exam subject '{title}' deleted.")
    return redirect('teacher_dashboard')
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
    if request.method == 'POST':
        form = StudentCreateForm(request.POST)
        if form.is_valid():
            student = form.save()
            course = form.cleaned_data.get('course')
            if course:
                TeacherStudentAssignment.objects.create(teacher=request.user, student=student, course=course)
            messages.success(request, f"Student {student.username} created.")
            return redirect('teacher_dashboard')
    else:
        form = StudentCreateForm()
    return render(request, 'teachers/create_student.html', {'form': form})


@login_required
@user_passes_test(is_teacher)
def teacher_proctoring_dashboard(request):
    # Show only sessions for the students assigned to this teacher
    assigned_students = TeacherStudentAssignment.objects.filter(teacher=request.user).values_list('student', flat=True)
    sessions = QuizSession.objects.filter(student__in=assigned_students).exclude(status='ongoing').prefetch_related('proctoring_logs').order_by('-start_time')
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
