from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views
from django.contrib.auth import views as auth_views 

urlpatterns = [
    # --- General Pages ---
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('privacy/', views.privacy_policy, name='privacy_policy'),
    path('faq/', views.faq, name='faq'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile_view, name='edit_profile'),
    path('dashboard/', views.instructor_dashboard, name='instructor_dashboard'),

    # --- Authentication ---
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # --- Instructor: Creating Content ---
    path('course/create/', views.create_course, name='create_course'),
    path('course/<int:course_id>/edit/', views.edit_course, name='edit_course'),
    path('course/<int:course_id>/add-video/', views.add_video, name='add_video'),
    path('video/<int:video_id>/add-quiz/', views.add_quiz, name='add_quiz'),

    # --- Student: Watching & Quizzing ---
    path('course/<int:course_id>/lesson/<int:video_order>/', views.course_viewer, name='course_viewer'),
    
    # CRITICAL FIX: This allows the "Take Quiz" button to work (Now includes AI Proctoring!)
    path('video/<int:video_id>/take-quiz/', views.take_quiz, name='take_quiz'),
    # Standalone Exam Papers
    path('exam/<int:exam_id>/start/', views.start_exam, name='start_exam'),

    path('mentors/', views.mentors, name='mentors'),
    path('contact/', views.contact, name='contact'),
    path('courses/', views.course_list, name='course_list'), 
    path('course/<int:course_id>/request-access/', views.request_course_access, name='request_course_access'),
    path('course/<int:course_id>/checkout/', views.course_checkout, name='course_checkout'),

    # --- Video & Quiz Management ---
    path('video/<int:video_id>/delete/', views.delete_video, name='delete_video'),
    path('video/<int:video_id>/edit/', views.edit_video, name='edit_video'),
    path('quiz/<int:quiz_id>/delete/', views.delete_quiz, name='delete_quiz'),
    
    # --- Student Management ---
    path('student/<int:student_id>/view/', views.student_detail, name='student_detail'),
    path('student/<int:student_id>/delete/', views.delete_student, name='delete_student'),
    path('students/', views.student_list, name='student_list'), 
    path('dashboard/user/<int:user_id>/toggle-status/', views.toggle_portal_user_status, name='toggle_portal_user_status'),
    path('dashboard/user/<int:user_id>/delete/', views.delete_portal_user, name='delete_portal_user'),

    # --- OTP VERIFICATION (SIGNUP) ---
    # This expects 6 digits (Don't touch this)
    path('verify-otp/', views.verify_otp, name='verify_otp'),

    path('course/<int:course_id>/certificate/', views.certificate_view, name='certificate_view'),
    path('video/<int:video_id>/complete/', views.complete_lesson, name='complete_lesson'),

    # --- FORGOT PASSWORD FLOW ---
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    
    # ✅ FIX: Changed URL to 'verify-reset-code/' to avoid conflict with Signup
    path('verify-reset-code/', views.verify_otp_view, name='enter_otp'),
    
    path('reset-new-password/', views.reset_new_password_view, name='reset_new_password'),
    path('course/<int:course_id>/review/', views.add_review, name='add_review'),
    path('video/<int:video_id>/comment/', views.add_comment, name='add_comment'),
    path('video/<int:video_id>/comment/<int:parent_id>/', views.add_comment, name='reply_comment'),

    # ==========================================================
    # 🚀 AI PROCTORING & QUIZ SESSIONS (UPDATED)
    # ==========================================================
    
    # The background URL that receives the webcam snapshots from the student
    path('quiz/session/<int:session_id>/process_frame/', views.process_quiz_frame, name='process_frame'),
    
    # Instructor Dashboard URLs to review flagged students
    path('instructor/proctoring/', views.admin_proctoring_dashboard, name='admin_proctoring_dashboard'),
    path('instructor/proctoring/review/<int:session_id>/', views.review_quiz_session, name='review_quiz_session'),
]

# --- Media File Configuration ---
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
