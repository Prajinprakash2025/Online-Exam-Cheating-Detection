from django.db import models
from django.conf import settings
from courses.models import Course


class TeacherStudentAssignment(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_assignments'
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_teacher_assignments'
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='teacher_assignments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('teacher', 'student', 'course')

    def __str__(self):
        return f"{self.teacher.username} -> {self.student.username} ({self.course.title})"
