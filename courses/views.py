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
from django.contrib.auth.forms import AuthenticationForm
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.core.files.base import ContentFile

from .models import Course, Video, User, Progress, Quiz, Enrollment, Review, Comment, QuizSession, ProctoringLog
from .forms import CourseForm, VideoForm, QuizForm, StudentSignupForm, ReviewForm, CommentForm

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
    context = {'conductors': conductors}

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

def course_list(request):
    query = request.GET.get('q')
    courses = Course.objects.annotate(video_count=Count('videos'))

    if query:
        courses = courses.filter(
            Q(title__icontains=query) | 
            Q(description__icontains=query) 
        )

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
    # Student self-signup is disabled per new "Exam Portal" logic.
    # Redirect to a page explaining that access is granted by Teachers/Examiners.
    return render(request, 'restricted_signup.html')

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
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
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
    video = get_object_or_404(Video, course=course, order=video_order)
    
    enrollment, created = Enrollment.objects.get_or_create(
        student=request.user, 
        course=course
    )

    if video_order > enrollment.current_lesson_index:
        return render(request, 'locked.html', {'course': course})

    all_videos = course.videos.all().order_by('order')
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
    
    # 2. START TIMER (Giving them 15 minutes by default for a quiz)
    if created or not session.end_time:
        session.end_time = timezone.now() + timedelta(minutes=15)
        session.save()

    remaining_time = (session.end_time - timezone.now()).total_seconds()

    # 3. GRADING & SUBMISSION LOGIC
    if request.method == 'POST' or remaining_time <= 0:
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
        'remaining_time': int(remaining_time)
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
    
    # 2. START TIMER
    if created or not session.end_time:
        session.end_time = timezone.now() + timedelta(minutes=exam.duration_minutes)
        session.save()

    remaining_time = (session.end_time - timezone.now()).total_seconds()

    # 3. GRADING & SUBMISSION LOGIC
    if request.method == 'POST' or remaining_time <= 0:
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
        'remaining_time': int(remaining_time)
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

# 🚀 Load OpenCV AI Models globally to make it super fast
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
alt_face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
profile_face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# Secondary detector to reduce “no face” false negatives when a face is masked or at an angle.
hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())


def _detect_faces(gray_frame):
    """
    Cascade ensemble with eye-validation to drop false positives
    (e.g., phones or background mistaken as faces).
    """
    cascades = (face_cascade, alt_face_cascade, profile_face_cascade)
    for cascade in cascades:
        faces = cascade.detectMultiScale(
            gray_frame,
            scaleFactor=1.05,
            minNeighbors=4,
            minSize=(60, 60)
        )
        filtered = []
        for (x, y, w, h) in faces:
            # Reject very small detections
            if w < 60 or h < 60:
                continue
            roi = gray_frame[y:y+h, x:x+w]
            eyes = eye_cascade.detectMultiScale(
                roi, scaleFactor=1.1, minNeighbors=4, minSize=(12, 12)
            )
            # Keep only detections that contain eyes to avoid counting phones/objects as faces
            if len(eyes) > 0:
                filtered.append((x, y, w, h))
        if filtered:
            return filtered
        if len(faces) > 0:
            return list(faces)
    return []


def _detect_people(frame):
    """
    Lightweight pedestrian detector (HOG+SVM). Helps confirm presence of humans
    even if faces are not picked up by cascades.
    """
    people, weights = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
    return people, weights


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
        if area < 0.005 * frame_area or area > 0.08 * frame_area:
            continue

        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if 4 <= len(approx) <= 8:
            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / float(h) if h else 0
            # Typical phone aspect ratio when held vertically
            if 0.45 <= aspect <= 0.8:
                # If we have a face, require the phone to be near it; otherwise accept.
                if face_boxes:
                    for (fx, fy, fw, fh) in face_boxes:
                        if (fx - 80 <= x <= fx + fw + 80) and (fy - 40 <= y <= fy + fh + 120):
                            return True, (x, y, w, h)
                else:
                    # Fall back: only consider phones in the upper half of the frame
                    if y < frame.shape[0] * 0.7:
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


def _should_log_frame_violation(session_id, violation_type):
    immediate_types = {'multi_face', 'phone_detected'}
    if violation_type in immediate_types:
        cache.delete(f'proctor_clean_{session_id}')
        return True

    key = f'proctor_violation_{session_id}_{violation_type}'
    count = cache.get(key, 0) + 1
    cache.set(key, count, timeout=30)
    return count >= 2


def _reset_frame_violation_state(session_id):
    for violation_type in ('no_face', 'gaze_deviation', 'head_pose'):
        cache.delete(f'proctor_violation_{session_id}_{violation_type}')

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
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)

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

                # 1) CLEAR MULTI-FACE (only if real face detections >1)
                if len(faces) > 1:
                    violation_detected = True
                    violation_type = 'multi_face'
                    confidence = 0.96
                    cv2.putText(frame, "ALERT: MULTIPLE PERSONS", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    for (x, y, w, h) in faces:
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 3)

                # 2) PHONE DETECTED (check before gaze to avoid false multi-face)
                elif phone_found:
                    violation_detected = True
                    violation_type = 'phone_detected'
                    confidence = 0.90
                    px, py, pw, ph = phone_box
                    cv2.rectangle(frame, (px, py), (px+pw, py+ph), (0, 0, 255), 3)
                    cv2.putText(frame, "ALERT: PHONE DETECTED", (px, max(30, py-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                # 3) NO FACE FOUND
                elif len(faces) == 0:
                    if len(people) > 1:
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
                    
                    if len(eyes) == 0:
                        violation_detected = True
                        violation_type = 'gaze_deviation'
                        confidence = 0.85
                        
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
                    if _should_log_frame_violation(session.id, violation_type):
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

    context = {
        'courses': courses,
        'total_students': total_students_count,
        'all_students': students,
        'recent_activity': recent_activity,
        'quiz_sessions': quiz_sessions, 
        'examiners': examiners,
    }
    return render(request, 'dashboard.html', context)

@user_passes_test(is_admin)
def admin_proctoring_dashboard(request):
    sessions = QuizSession.objects.exclude(status='ongoing').order_by('-start_time')
    return render(request, 'admin_proctoring_dashboard.html', {'sessions': sessions})

@user_passes_test(is_admin)
def review_quiz_session(request, session_id):
    session = get_object_or_404(QuizSession, id=session_id)
    logs = session.proctoring_logs.all().order_by('timestamp')

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
        'logs': logs
    }
    return render(request, 'review_quiz_session.html', context)

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
def delete_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    video.delete()
    return redirect('instructor_dashboard')

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
    return redirect('instructor_dashboard')

@user_passes_test(is_admin)
def delete_student(request, student_id):
    student = get_object_or_404(User, id=student_id)
    if not student.is_superuser: 
        student.delete()
    return redirect('instructor_dashboard')
