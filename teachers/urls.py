from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.teacher_login, name='teacher_login'),
    path('logout/', views.teacher_logout, name='teacher_logout'),
    path('dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('exam/<int:video_id>/manage/', views.teacher_manage_exam, name='teacher_manage_exam'),
    path('assign/', views.assign_teacher, name='assign_teacher'),
    path('create/', views.create_teacher, name='create_teacher'),
    path('student/create/', views.create_student, name='teacher_create_student'),
    path('proctoring/', views.teacher_proctoring_dashboard, name='teacher_proctoring_dashboard'),
    path('proctoring/review/<int:session_id>/', views.teacher_review_exam, name='teacher_review_exam'),
    # Exam Paper Routes
    path('exam/delete/<int:exam_id>/', views.delete_exam, name='delete_exam'),
    path('exam/<int:exam_id>/questions/', views.teacher_exam_questions, name='teacher_exam_questions'),
    path('exam/question/delete/<int:question_id>/', views.delete_exam_question, name='delete_exam_question'),
    path('exam/session/grade/<int:session_id>/', views.grade_exam_session, name='grade_exam_session'),
    path('student/<int:student_id>/exams/', views.student_exam_status, name='student_exam_status'),
    path('student/<int:student_id>/exam-assignment/assign/', views.assign_or_reexam_student, name='assign_or_reexam_student'),
    path('student/<int:student_id>/exam-assignment/<int:assignment_id>/cancel/', views.cancel_student_exam_assignment, name='cancel_student_exam_assignment'),
    path('student/delete/<int:student_id>/', views.delete_student_assignment, name='delete_student_assignment'),
]
