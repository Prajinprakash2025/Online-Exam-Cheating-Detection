from courses.models import User
seen = set()
for u in User.objects.all():
    email = u.email.lower().strip() if u.email else ""
    if not email or email in seen:
        new_email = f"{u.username}+{email}" if email else f"{u.username}@temp.com"
        u.email = new_email
        u.save()
        print(f"Fixed {u.username}: {new_email}")
    seen.add(u.email.lower().strip())
print("Data fix complete.")
