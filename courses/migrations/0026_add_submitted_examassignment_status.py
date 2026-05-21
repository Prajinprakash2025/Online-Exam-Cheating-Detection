from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0025_remove_examquestion_correct_option_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='examassignment',
            name='status',
            field=models.CharField(
                choices=[
                    ('assigned', 'Assigned'),
                    ('submitted', 'Submitted'),
                    ('completed', 'Completed'),
                ],
                default='assigned',
                max_length=20,
            ),
        ),
    ]
