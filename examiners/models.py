from django.db import models
from django.conf import settings


class ExaminerTeacherAssignment(models.Model):
    examiner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='examiner_assignments'
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_examiner_assignments'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('examiner', 'teacher')

    def __str__(self):
        return f"{self.examiner.username} -> {self.teacher.username}"
