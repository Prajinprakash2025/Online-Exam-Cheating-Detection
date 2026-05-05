from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.examiner_signup, name='examiner_signup'),
    path('login/', views.examiner_login, name='examiner_login'),
    path('logout/', views.examiner_logout, name='examiner_logout'),
    path('dashboard/', views.examiner_dashboard, name='examiner_dashboard'),
    path('conductor/delete/<int:teacher_id>/', views.delete_conductor, name='delete_conductor'),
    path('candidate/delete/<int:student_id>/', views.delete_candidate, name='delete_candidate'),
    path('subject/delete/<int:course_id>/', views.delete_subject, name='delete_subject'),
    path('create_teacher/', views.create_teacher, name='examiner_create_teacher'),
]
