from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    # --- General Pages ---
    path('', views.home, name='home'),
    path('profile/', views.profile_view, name='profile'),
    path('dashboard/', views.instructor_dashboard, name='instructor_dashboard'),

    # --- Authentication ---
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # --- Instructor: Creating Content ---
    path('course/create/', views.create_course, name='create_course'),
    path('course/<int:course_id>/add-video/', views.add_video, name='add_video'),
    path('video/<int:video_id>/add-quiz/', views.add_quiz, name='add_quiz'),

    # --- Student: Watching & Quizzing ---
    path('course/<int:course_id>/lesson/<int:video_order>/', views.course_viewer, name='course_viewer'),
    
    # CRITICAL FIX: This allows the "Take Quiz" button to work
    path('video/<int:video_id>/take-quiz/', views.take_quiz, name='take_quiz'),

    path('mentors/', views.mentors, name='mentors'),
    path('contact/', views.contact, name='contact'),
    path('courses/', views.course_list, name='course_list'), # New separate page

    path('video/<int:video_id>/delete/', views.delete_video, name='delete_video'),
    path('video/<int:video_id>/edit/', views.edit_video, name='edit_video'),

    # QUIZ MANAGEMENT
    path('quiz/<int:quiz_id>/delete/', views.delete_quiz, name='delete_quiz'),
    
    # STUDENT MANAGEMENT
    path('student/<int:student_id>/view/', views.student_detail, name='student_detail'),
    path('student/<int:student_id>/delete/', views.delete_student, name='delete_student'),
    path('students/', views.student_list, name='student_list'), # <--- ADD THIS
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('course/<int:course_id>/certificate/', views.certificate_view, name='certificate_view'),
    path('video/<int:video_id>/complete/', views.complete_lesson, name='complete_lesson'),

]

# --- Media File Configuration (Fixes broken images) ---
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)