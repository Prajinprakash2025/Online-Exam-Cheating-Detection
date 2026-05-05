from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth import get_user_model
from .forms import ExaminerSignupForm, ExaminerStudentCreateForm, SubjectForm
from teachers.forms import TeacherCreateForm
from teachers.models import TeacherStudentAssignment
from courses.models import Course, QuizSession, ProctoringLog
from .models import ExaminerTeacherAssignment

User = get_user_model()


def examiner_signup(request):
    if request.method == 'POST':
        form = ExaminerSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Automatic login after signup
            login(request, user)
            messages.success(request, "Conductor account created successfully. Welcome to the Master Hub!")
            return redirect('examiner_dashboard')
    else:
        form = ExaminerSignupForm()
    return render(request, 'examiners/examiner_signup.html', {'form': form})


def examiner_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, username=email, password=password)
        if user and user.is_examiner:
            login(request, user)
            return redirect('examiner_dashboard')
        messages.error(request, "Invalid conductor credentials.")
    return render(request, 'examiners/examiner_login.html')


@login_required
def examiner_logout(request):
    logout(request)
    return redirect('examiner_login')


def is_examiner(user):
    return user.is_authenticated and user.is_examiner


@login_required
@user_passes_test(is_examiner)
def examiner_dashboard(request):
    examiner = request.user
    assignments = ExaminerTeacherAssignment.objects.filter(examiner=examiner).select_related('teacher')
    teachers = [a.teacher for a in assignments]
    teacher_ids = [t.id for t in teachers]
    
    # Handle POST for Registration
    teacher_form = TeacherCreateForm()
    candidate_form = ExaminerStudentCreateForm(examiner=examiner)
    subject_form = SubjectForm()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'register_conductor':
            teacher_form = TeacherCreateForm(request.POST)
            if teacher_form.is_valid():
                teacher = teacher_form.save()
                ExaminerTeacherAssignment.objects.create(examiner=examiner, teacher=teacher)
                messages.success(request, f"Teacher {teacher.username} registered successfully.")
                return redirect('/examiners/dashboard/#conductors')
        
        elif action == 'register_candidate':
            candidate_form = ExaminerStudentCreateForm(request.POST, examiner=examiner)
            if candidate_form.is_valid():
                candidate = candidate_form.save()
                messages.success(request, f"Candidate {candidate.username} registered and assigned.")
                return redirect('/examiners/dashboard/#candidates')
        
        elif action == 'register_subject':
            subject_form = SubjectForm(request.POST, request.FILES)
            if subject_form.is_valid():
                subject = subject_form.save()
                messages.success(request, f"New exam subject '{subject.title}' created.")
                return redirect('/examiners/dashboard/#subjects')
        
        elif action == 'edit_subject':
            subject_id = request.POST.get('subject_id')
            subject = get_object_or_404(Course, id=subject_id)
            subject_form = SubjectForm(request.POST, request.FILES, instance=subject)
            if subject_form.is_valid():
                subject_form.save()
                messages.success(request, f"Subject '{subject.title}' updated successfully.")
                return redirect('/examiners/dashboard/#subjects')

        elif action == 'edit_conductor':
            conductor_id = request.POST.get('conductor_id')
            conductor = get_object_or_404(User, id=conductor_id, is_teacher=True)
            conductor.first_name = request.POST.get('first_name', conductor.first_name)
            conductor.last_name = request.POST.get('last_name', conductor.last_name)
            conductor.email = request.POST.get('email', conductor.email)
            conductor.save()
            messages.success(request, f"Conductor {conductor.username} updated.")
            return redirect('/examiners/dashboard/#conductors')

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
    managed_student_assignments = TeacherStudentAssignment.objects.filter(
        teacher_id__in=teacher_ids
    ).select_related('teacher', 'student', 'course')
    
    managed_student_ids = [a.student_id for a in managed_student_assignments]
    
    total_candidates = len(set(managed_student_ids))
    recent_sessions = QuizSession.objects.filter(
        student_id__in=managed_student_ids
    ).exclude(status='ongoing').select_related('student', 'video__course').order_by('-start_time')[:10]
    
    flagged_sessions_count = QuizSession.objects.filter(
        student_id__in=managed_student_ids,
        status='flagged'
    ).count()

    return render(request, 'examiners/examiner_dashboard.html', {
        'teachers': teachers,
        'candidates': managed_student_assignments,
        'all_subjects': Course.objects.all().order_by('-created_at'),
        'total_teachers': len(teachers),
        'total_candidates': total_candidates,
        'flagged_count': flagged_sessions_count,
        'recent_sessions': recent_sessions,
        'teacher_form': teacher_form,
        'candidate_form': candidate_form,
        'subject_form': subject_form
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
