from django.db import migrations


def replace_dollar_with_rupee(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    for n in Notification.objects.filter(message__contains="$"):
        n.message = n.message.replace("$", "₹")
        n.save(update_fields=["message"])
    for n in Notification.objects.filter(title__contains="$"):
        n.title = n.title.replace("$", "₹")
        n.save(update_fields=["title"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0005_alter_notification_notification_type"),
    ]

    operations = [
        migrations.RunPython(replace_dollar_with_rupee, reverse_code=noop),
    ]
